import csv
import logging
import subprocess as sp
import threading
from queue import Empty

from beholder.defaults import *


def finalize_recording(pipe, partial_path, final_path):
    """Wait for the encoder to finish, then rewrite the fragmented recording into a regular MP4.

    Runs in its own thread so a Writer is not blocked while its file is being finalized.
    The partial file is only removed once the final file was written successfully.
    """
    try:
        pipe.wait(timeout=FFMPEG_STOP_TIMEOUT)
    except sp.TimeoutExpired:
        logging.error(f'FFMPEG did not finish {partial_path.name} within {FFMPEG_STOP_TIMEOUT} s, killing it.')
        pipe.kill()
        pipe.wait()

    if pipe.returncode:
        logging.error(f'FFMPEG exited with code {pipe.returncode} for {partial_path.name}')

    if not partial_path.exists() or not partial_path.stat().st_size:
        logging.error(f'Nothing was recorded to {partial_path}')
        return

    cmd = FFMPEG_REMUX_COMMAND + ['-i', str(partial_path)] + FFMPEG_REMUX_OUTPUT_ARGS + [str(final_path)]
    logging.debug(' '.join(cmd))
    try:
        result = sp.run(cmd, stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.PIPE)
        ok = result.returncode == 0 and final_path.exists() and final_path.stat().st_size > 0
        error = result.stderr.decode(errors='replace').strip()
    except OSError as e:
        ok = False
        error = str(e)

    if ok:
        partial_path.unlink()
        logging.debug(f'Finalized {final_path.name}')
    else:
        # Keep the partial file, it is a playable recording. Remove the broken final file.
        if final_path.exists():
            final_path.unlink()
        logging.error(f'Could not finalize {final_path.name}, recording kept as {partial_path.name}. {error}')


class Writer(threading.Thread):
    def __init__(self, cfg, in_queue, ev_alive, ev_recording, ev_trial_active, main_thread, idx=0):
        super().__init__()
        self.id = idx
        self.cfg = cfg

        self.name = 'Writer #{:02d}'.format(self.id)
        self.writer_pipe = None
        self.out_path = None
        self.partial_path = None
        self.log_file = None
        self.log_csv = None
        self.log_csv_header_written = False
        self.logger = None

        self.n_frames = 0

        self.width = None
        self.height = None
        self.frame = None

        self.in_queue = in_queue
        self._ev_stop = ev_alive
        self._ev_recording = ev_recording
        self._ev_trial_active = ev_trial_active
        self.n_retry = 0

        self.parent = main_thread

        self.recording = False
        logging.debug('Writer initialization done!')

    def start_recording(self):
        # Video output object
        rec_path = self.parent.recording_path
        rec_ts = self.parent.recording_ts
        if rec_path is None or rec_ts is None:
            # recording was stopped again before we got to start
            return
        logging.debug('Starting Recording in {}'.format(rec_path))

        # Release whatever a previous failed attempt left open
        self.close_outputs()

        # A retry after an encoder failure gets its own file, so the first part of the
        # recording is kept (and can be finalized) instead of being overwritten.
        retry = '_retry{}'.format(self.n_retry) if self.n_retry else ''
        self.out_path = rec_path / 'eye{:02d}_{}{}.mp4'.format(self.id + 1, rec_ts, retry)
        self.partial_path = self.out_path.with_name(self.out_path.stem + PARTIAL_SUFFIX)
        ffmpeg_cmd = FFMPEG_COMMAND + [str(self.partial_path)]
        logging.debug(' '.join(ffmpeg_cmd))

        try:
            self.writer_pipe = sp.Popen(ffmpeg_cmd, stdin=sp.PIPE)
        except OSError as e:
            logging.error(f'Could not start FFMPEG ({ffmpeg_cmd[0]}): {e}')
            self.writer_pipe = None
            self.recording = False
            return

        self.log_file = open(self.out_path.with_suffix('.meta'), 'w', newline='')
        self.log_csv = csv.writer(self.log_file)
        self.log_csv_header_written = False
        self.n_frames = 0

        self.recording = self.writer_pipe.poll() is None

    def close_outputs(self):
        """Close the encoder input and the metadata file, hand the video file over for finalizing."""
        if self.writer_pipe is not None:
            try:
                self.writer_pipe.stdin.close()
            except OSError:
                # FFMPEG already died, nothing left to flush into
                pass
            threading.Thread(target=finalize_recording,
                             args=(self.writer_pipe, self.partial_path, self.out_path),
                             name='Finalize #{:02d}'.format(self.id)).start()
            self.writer_pipe = None

        if self.log_file is not None and not self.log_file.closed:
            self.log_csv = None
            self.log_file.close()
        self.log_file = None

    def stop_recording(self):
        if self.recording:
            logging.debug('Stopping Recording')

        self.recording = False
        self.close_outputs()

        self.logger = None
        self.n_retry = 0

    def run(self):
        logging.debug('Starting loop in {}!'.format(self.name))
        try:
            while not self._ev_stop.is_set():
                try:
                    metadata, frame = self.in_queue.get(timeout=.5)
                except Empty:
                    # No frame from the source. Still follow the recording state below, or a
                    # recording could not be stopped while its camera is disconnected.
                    metadata, frame = None, None

                rec = self._ev_recording.is_set()

                if not rec and (self.recording or self.writer_pipe is not None or self.n_retry):
                    self.stop_recording()

                # Only start once there is a frame to write
                if rec and not self.recording and frame is not None:
                    if self.n_retry < NUM_PIPE_RETRIES:
                        if self.n_retry:
                            logging.warning(f'Retry {self.n_retry + 1} to start recording.')
                        self.start_recording()
                        self.n_retry += 1

                    elif self.n_retry == NUM_PIPE_RETRIES:
                        logging.error('Failed to start recording, maximum number of retries exceeded!')
                        self.n_retry += 1

                if self.recording and frame is not None:
                    if self.writer_pipe is None:
                        logging.error('Attempted to write to failed Writer!')
                        self.recording = False
                    else:
                        try:
                            self.writer_pipe.stdin.write(frame)
                        except BrokenPipeError:
                            logging.error('FFMPEG Pipe closed unexpectedly.')
                            self.recording = False
                        else:
                            if not self.log_csv_header_written:
                                self.log_csv.writerow(metadata.keys())
                                self.log_csv_header_written = True
                            self.log_csv.writerow(metadata.values())
                            self.n_frames += 1
                            if not self.n_frames % META_FLUSH_INTERVAL:
                                self.log_file.flush()

            logging.debug('Stopping loop in {}!'.format(self.name))
        finally:
            # Also on shutdown or an unexpected error: close the files of a running recording
            self.stop_recording()
