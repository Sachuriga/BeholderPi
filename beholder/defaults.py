REC_BUTTON_DEBOUNCE = 2

N_FRAMES_FPS_LOG = 20

PIEYE_SUB_TOPIC = b'piEye'
PIEYE_METADATA_DTYPE = [('name', 'S8'), ('frame_index', '<i8'),
                        ('frame_gpu_ts', '<i8'), ('callback_gpu_ts', '<i8'),
                        ('callback_clock_ts', '<f8')]

NUM_PIPE_RETRIES = 3
DISK_MIN_GB = 10
DISK_LOW_GB = 30

# name (or path) of the ffmpeg executable. Used to differentiate system
# installed ffmpeg from our hardware enabled/customized variant
FFMPEG_BINARY = 'ffmpeg_gpu'
# FFMPEG_COMMAND = [FFMPEG_BINARY,
#                   '-y',
#                   '-hide_banner',
#                   '-loglevel', 'error',
#                   '-nostats',
#
#                   # '-hwaccel', 'cuvid',
#                   # '-c:v', 'mjpeg_cuvid',
#
#                   # '-pix_fmt', 'yuvj420p',
#                   '-f', 'mjpeg',
#                   '-r', '30.',
#                   '-i', '-',
# # '-filter:v hwupload_cuda,scale_npp=format=nv12:interp_algo=lanczos,hwdownload,format=nv12',
#                   # '-c:v', 'libx264',
#                   '-c:v', 'h264_nvenc',
#                   '-b:v', '350k',
#                   # '-gpu', 'list',
#                   # '-c:v', 'copy',
#                   '-preset', 'slow',
#                   '-pix_fmt', 'yuv420p',
#                   # '-profile:v', 'high',
#                   '-vf', 'hqdn3d'
#                   ]

# Arguments shared by all ffmpeg invocations
FFMPEG_GLOBAL_ARGS = ['-y', '-hide_banner', '-loglevel', 'error', '-nostats']

# Available encoders for recording. Selected with the `encoder` key of the beholder
# configuration file. 'auto' takes the first one in ENCODER_AUTO_ORDER whose binary is installed.
#   nvenc: decode and encode on an NVIDIA GPU, needs the custom built `ffmpeg_gpu`
#   x264:  encode on the CPU with the stock ffmpeg of the distribution (`apt install ffmpeg`)
ENCODERS = {
    'nvenc': {'binary': FFMPEG_BINARY,
              'input': ['-vsync', '0', '-hwaccel', 'cuvid', '-c:v', 'mjpeg_cuvid'],
              'output': ['-c:v', 'h264_nvenc', '-preset', 'slow']},
    'x264': {'binary': 'ffmpeg',
             'input': ['-vsync', '0'],
             # one ffmpeg runs per camera, keep each from grabbing all cores
             'output': ['-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2']},
}
ENCODER_AUTO_ORDER = ['nvenc', 'x264']

# Target video bitrate per camera, overridden by the `record_bitrate` configuration key.
# The former 400k was tuned for 600x800 frames; at 1232x1640 it starves the encoder and
# everything that moves turns into a smear.
RECORD_BITRATE = '3M'

# Record as fragmented MP4: the file stays readable up to the last fragment if beholder,
# ffmpeg or the machine dies mid-recording.
FFMPEG_RECORD_CONTAINER_ARGS = ['-movflags', '+frag_keyframe+empty_moov+default_base_moof',
                                '-frag_duration', '2000000',  # microseconds
                                # write every finished fragment to disk right away, ffmpeg otherwise
                                # holds back ~0.5 MB (several seconds of video) in its output buffer
                                '-flush_packets', '1']

# After a clean stop the fragmented recording is rewritten (stream copy, no re-encode) into a
# regular MP4 with the index at the front:
#   [binary] + FFMPEG_GLOBAL_ARGS + ['-i', partial_path] + FFMPEG_REMUX_OUTPUT_ARGS + [final_path]
FFMPEG_REMUX_OUTPUT_ARGS = ['-c', 'copy', '-movflags', 'faststart']

# Suffix of the in-progress recording, replaces '.mp4' until finalized
PARTIAL_SUFFIX = '.partial.mp4'

# seconds to wait for the encoder to finish after its input was closed
FFMPEG_STOP_TIMEOUT = 60

# write the frame metadata to disk every N frames
META_FLUSH_INTERVAL = 30

SOCKET_RECV_TIMEOUT = 1000
WRITE_QUEUE_LENGTH = 150  # frames

FORCE_RECORDING_ON_TRIAL = True
