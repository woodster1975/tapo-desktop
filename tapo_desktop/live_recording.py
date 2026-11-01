"""Save compressed camera packets directly; never decode or expose the RTSP URL."""
from fractions import Fraction
import os
from pathlib import Path
import time
from urllib.parse import quote
import uuid
import math

from .storage import UserError, export_clip


def camera_url(data):
    # Used in memory only, never in process arguments, output or settings.
    return ('rtsp://' + quote(data['username'], safe='') + ':' +
            quote(data['password'], safe='') + '@' + data['host'] +
            ':554/' + data['stream'])


def normalize_packet_clock(packet, origin, previous=None):
    """Repair invalid/overlapping camera clocks without changing video bytes."""
    base=packet.time_base
    offset=int(Fraction(origin)/base)
    dts=packet.dts-offset
    pts=packet.pts-offset if packet.pts is not None else dts
    # Matroska uses millisecond timestamps; enforce ordering after rescaling.
    step=max(1,math.ceil(Fraction(1,1000)/base))
    if previous is not None and dts<previous+step:
        adjustment=previous+step-dts;dts+=adjustment;pts+=adjustment
    packet.dts=dts;packet.pts=max(pts,dts)
    return dts


def record_stream(source, destination, emit, cancelled, *, network=True):
    """Remux to a recoverable Matroska file, publishing without overwriting.

    A second RTSP connection is required; display decoding stays with Qt.
    Keep original video and compatible audio, starting at a video keyframe.
    G.711 audio is expanded to PCM because Matroska rejects its codec tag.
    """
    import av
    av.logging.set_level(av.logging.PANIC)
    destination = Path(destination)
    if destination.suffix.lower() != '.mkv':
        raise UserError('Choose an MKV file for live recording.')
    if destination.exists():
        raise UserError('A recording already exists with that name. Choose another name.')
    if cancelled():return {'recorded': False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name('.tapo-' + uuid.uuid4().hex + '.partial.mkv')
    packets = 0; elapsed = 0.0; audio = False; interrupted = False; interruption_kind = None
    origin = None; last_notice = 0.0; problem = None; converted = set(); audio_clock = {}
    stage = 'read'; interruption_stage = None; last_dts = {}
    try:
        with os.fdopen(os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as handle:
            options = {'rtsp_transport': 'tcp'} if network else {}
            with av.open(source, options=options, timeout=(10, 5)) as input_file:
                streams = [s for s in input_file.streams if s.type in ('video', 'audio')]
                if not any(s.type == 'video' for s in streams):
                    raise UserError('The camera did not provide a video stream.')
                with av.open(handle, 'w', format='matroska',
                             options={'cluster_time_limit': '1000'}) as output:
                    mapping = {}
                    for stream in streams:
                        try:mapping[stream.index] = output.add_stream_from_template(stream)
                        except ValueError:
                            if stream.type != 'audio':raise
                            mapping[stream.index] = output.add_stream('pcm_s16le',
                                rate=stream.codec_context.sample_rate or 8000,
                                layout=stream.codec_context.layout.name or 'mono')
                            converted.add(stream.index)
                    try:
                        for packet in input_file.demux(*streams):
                            if cancelled():break
                            if not packet.size or packet.dts is None:continue
                            kind = packet.stream.type
                            base = packet.time_base or packet.stream.time_base
                            timestamp = packet.dts * base
                            if origin is None:
                                if kind != 'video' or not packet.is_keyframe:continue
                                origin = timestamp
                            if timestamp < origin:continue
                            elapsed = max(elapsed, float(timestamp - origin))
                            target = mapping[packet.stream.index]
                            if packet.stream.index in converted:
                                stage = 'audio_decode'
                                for frame in packet.decode():
                                    rate = frame.sample_rate
                                    # Camera G.711 packet timestamps can overlap.
                                    # Encode on a monotonic sample clock, preserving
                                    # forward gaps rather than rejecting valid audio.
                                    start = max(0,round((timestamp-origin)*rate))
                                    index = packet.stream.index
                                    frame.pts = max(audio_clock.get(index,start),start)
                                    frame.time_base = Fraction(1,rate)
                                    audio_clock[index] = frame.pts + frame.samples
                                    stage = 'audio_encode'
                                    for encoded in target.encode(frame):
                                        stage = 'audio_mux';output.mux(encoded)
                            else:
                                index=packet.stream.index
                                last_dts[index]=normalize_packet_clock(packet,origin,last_dts.get(index))
                                packet.stream = target
                                stage = 'video_mux' if kind == 'video' else 'audio_mux'
                                output.mux(packet)
                            packets += 1
                            audio = audio or kind == 'audio'
                            now = time.monotonic()
                            if packets == 1:
                                emit('recording', seconds=elapsed)
                            if now - last_notice >= 1:
                                last_notice = now
                                emit('recording_progress', seconds=elapsed)
                            stage = 'read'
                        else:
                            interrupted = network and not cancelled()
                    except Exception as exc:
                        if not packets:raise
                        # Retain received footage on a network interruption. Disk
                        # errors must surface rather than claiming a complete save.
                        if isinstance(exc, OSError) and getattr(exc, 'errno', None) in (5, 13, 28):raise
                        interrupted = not cancelled()
                        interruption_kind = type(exc).__name__
                        interruption_stage = stage
                    for index in converted:
                        for encoded in mapping[index].encode(None):output.mux(encoded)
                handle.flush();os.fsync(handle.fileno())
    except Exception as exc:
        problem = exc
    if problem is not None:
        if not packets:partial.unlink(missing_ok=True)
        if not packets and cancelled():return {'recorded': False}
        raise UserError('Live recording could not be saved. Check the camera connection, '
                        'available disk space and recording folder. Any unfinished footage '
                        'is kept as a .partial.mkv file in that folder.') from None
    if not packets:
        partial.unlink(missing_ok=True)
        return {'recorded': False}
    try:
        try:os.link(partial, destination)
        except FileExistsError:
            raise UserError('The destination already exists. The new footage is kept as a .partial.mkv file.') from None
        except OSError:export_clip(partial, destination)
        partial.unlink()
    except UserError:raise
    except OSError:
        raise UserError('Could not finish saving. The footage is kept as a .partial.mkv file in the recording folder.') from None
    return {'recorded': True, 'path': str(destination), 'seconds': elapsed,
            'bytes': destination.stat().st_size, 'audio': audio, 'interrupted': interrupted,
            'audio_converted': bool(converted and audio), 'interruption_kind': interruption_kind,
            'interruption_stage': interruption_stage}
