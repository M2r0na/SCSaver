"""SCSaver multiplayer transport for euddraft 0.10.2.5.

Local launcher replies are staged only in local transport state. Gameplay values
and public completion/error events are changed only after MSQC verification.
"""
from __future__ import annotations
import sys
import eudplib as ep

if __name__ != "SCSaver":
    sys.modules["SCSaver"] = sys.modules[__name__]

MAGIC = b"SCSV0001"
PROTOCOL_VERSION = 6
CHUNK_CAPACITY = 64
MAX_VALUES = 4096
PACKET_HEADER = 2
SYNC_BUFFER_SIZE = MAX_VALUES + PACKET_HEADER
SIZE = 88
OFFLINE = 0
ONLINE = 1
TIMEOUT = 96

IDX_MAGIC0=0; IDX_MAGIC1=1; IDX_VERSION=2; IDX_SELF_PTR=3; IDX_SIZE=4
IDX_MAP_HASH=5; IDX_SCHEMA=6; IDX_FLAGS=7; IDX_MAP_HB=8
IDX_LAUNCHER_HB=9; IDX_LAUNCHER_STATUS=10; IDX_SESSION=11
IDX_SAVE_REQ=12; IDX_SAVE_ACK=13; IDX_LOAD_REQ=14; IDX_LOAD_ACK=15
IDX_RESULT=16; IDX_SLOT=17; IDX_PAYLOAD_COUNT=18; IDX_PAYLOAD0=19
IDX_ERROR=83; IDX_TOTAL_COUNT=84; IDX_CHUNK_INDEX=85; IDX_CHUNK_COUNT=86; IDX_CHUNK_SIZE=87

_DESCRIPTOR=None
_CONFIGURED=False
_BINDINGS=[]
_KEYS=set()
_FLAT=[]
_LOCKED=False

# Local transport state. Values in these objects may differ per client and must
# never be used directly as synchronized gameplay conditions.
_LAST_LAUNCHER_HB=ep.EUDArray([0])
_STALE=ep.EUDArray([TIMEOUT])
_CONNECTED=ep.EUDArray([0])
_LAST_SAVE_ACK=ep.EUDArray([0])
_LAST_LOAD_ACK=ep.EUDArray([0])
_LOCAL_MODE = ep.EUDArray([0])
_LOCAL_CHUNK = ep.EUDArray([0])
_LOCAL_SLOT = ep.EUDArray([0])
_LOCAL_PLAYER = ep.EUDArray([0])
_LOCAL_PACKET_READY=ep.EUDArray([0])
_LOCAL_PACKET_LENGTH=ep.EUDArray([0])
_LOCAL_PACKET=ep.EUDArray([0] * SYNC_BUFFER_SIZE)
_LOCAL_PROGRESS_TIMER = ep.EUDArray([0])
# Shared events. Only complete_shared_packet(), called after MSQC verification,
# changes these values.
_SHARED_BUSY=ep.EUDArray([0])
_SAVE_EVENT=ep.EUDArray([0])
_LOAD_EVENT=ep.EUDArray([0])
_FAIL_EVENT=ep.EUDArray([0])
_LAST_ERROR=ep.EUDArray([0])


def _magic():
    return [int.from_bytes(MAGIC[:4], "little"), int.from_bytes(MAGIC[4:], "little")]


def _hash(text):
    value=0x811C9DC5
    for byte in str(text).encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value or 1


def _ptr(epd):
    return epd * 4 + 0x58A364


# StarCraft built-in sounds. No map asset insertion is required.
LOAD_START_WAV = "sound\\glue\\swishin.wav"
OPERATION_DONE_WAV = "sound\\Misc\\TDrTra01.wav"
OPERATION_ERROR_WAV = "sound\\Misc\\Buzz.wav"

SAVE_START_TEXT = "\x07[SCSaver] \x04데이터를 저장하는 중입니다."
LOAD_START_TEXT = "\x07[SCSaver] \x04데이터를 불러오는 중입니다."
SAVE_DONE_TEXT = "\x07[SCSaver] \x04저장이 완료되었습니다."
LOAD_DONE_TEXT = "\x07[SCSaver] \x04불러오기가 완료되었습니다."
ERROR_TEXT = "\x08[SCSaver] 처리 중 오류가 발생했습니다."


def _run_for_player(player, callback):
    previous_cp = ep.f_getcurpl()
    ep.f_setcurpl(player)
    callback()
    ep.f_setcurpl(previous_cp)


def _play_wav_for_player(player, wav_path, repeat=False):
    def _play():
        # PlayWAV is emitted twice for the loading cue. This is a common reliable
        # trigger pattern and makes the short built-in swish cue clearly audible.
        ep.DoActions(ep.PlayWAV(wav_path))
        if repeat:
            ep.DoActions(ep.PlayWAV(wav_path))
    _run_for_player(player, _play)


def _print_for_player(player, text):
    def _print():
        # f_eprintf emits trigger code directly and must not be placed in DoActions.
        ep.f_eprintf(text)
    _run_for_player(player, _print)


def _notify_player(player, text, wav_path, repeat=False):
    _print_for_player(player, text)
    _play_wav_for_player(player, wav_path, repeat)

@ep.EUDFunc
def show_local_progress(player):
    """
    요청 플레이어에게 저장 또는 로드 진행 상태를 반복 출력합니다.

    반드시 scsaversync.eps의 IsUserCP() 안에서만 호출해야 합니다.
    """

    # 아무 작업도 진행 중이지 않다면 타이머만 초기화
    if ep.EUDIf()(
        _LOCAL_MODE[0].Exactly(0)
    ):
        _LOCAL_PROGRESS_TIMER[0] = 0
        ep.EUDReturn()

    ep.EUDEndIf()


    _LOCAL_PROGRESS_TIMER[0] += 1


    # 약 12 트리거 사이클마다 다시 출력
    #
    # 너무 자주 출력되면 18 또는 24로 높일 수 있습니다.
    if ep.EUDIf()(
        _LOCAL_PROGRESS_TIMER[0]
        .AtLeast(12)
    ):
        _LOCAL_PROGRESS_TIMER[0] = 0

        previous_cp = ep.f_getcurpl()

        ep.f_setcurpl(
            player
        )


        # 저장 진행 중
        if ep.EUDIf()(
            _LOCAL_MODE[0].Exactly(1)
        ):
            ep.f_eprintf(
                "\x07[SCSaver] "
                "\x04저장 중입니다. "
                "Page: \x03{}\x04 / \x03{}",
                _LOCAL_CHUNK[0] + 1,
                chunk_count(),
            )

        ep.EUDEndIf()


        # 로드 진행 중
        if ep.EUDIf()(
            _LOCAL_MODE[0].Exactly(2)
        ):
            ep.f_eprintf(
                "\x07[SCSaver] "
                "\x04불러오는 중입니다. "
                "Page: \x03{}\x04 / \x03{}",
                _LOCAL_CHUNK[0] + 1,
                chunk_count(),
            )

        ep.EUDEndIf()


        ep.f_setcurpl(
            previous_cp
        )

    ep.EUDEndIf()


def _print_save_progress(player):
    previous_cp = ep.f_getcurpl()

    ep.f_setcurpl(player)

    ep.f_eprintf(
        "\x07[SCSaver] "
        "\x04저장 중입니다. "
        "Page: \x03{}\x04 / \x03{}",
        _LOCAL_CHUNK[0] + 1,
        chunk_count(),
    )

    ep.f_setcurpl(previous_cp)


def _print_load_progress(player):
    previous_cp = ep.f_getcurpl()

    ep.f_setcurpl(player)

    ep.f_eprintf(
        "\x07[SCSaver] "
        "\x04불러오는 중입니다. "
        "Page: \x03{}\x04 / \x03{}",
        _LOCAL_CHUNK[0] + 1,
        chunk_count(),
    )

    ep.f_setcurpl(previous_cp)

def configure(map_id, schema_version=1):
    global _DESCRIPTOR, _CONFIGURED
    if _CONFIGURED:
        raise RuntimeError("SCSaver.configure() may only be called once")
    if not str(map_id).strip():
        raise RuntimeError("SCSaver map_id must not be empty")
    schema_version=int(schema_version)
    if schema_version < 1:
        raise RuntimeError("SCSaver schema_version must be at least 1")
    header=_magic()+[PROTOCOL_VERSION,0,SIZE,_hash(map_id),schema_version,1,0,0,OFFLINE,0,0,0,0,0,0,0,0]
    values=header+([0]*CHUNK_CAPACITY)+[0,0,0,0,0]
    if len(values) != SIZE:
        raise RuntimeError("SCSaver descriptor size mismatch")
    _DESCRIPTOR=ep.EUDArray(values)

    def _start(block=_DESCRIPTOR):
        ep.RawTrigger(actions=[
            ep.SetMemoryEPD(block._epd+IDX_MAGIC0,ep.SetTo,_magic()[0]),
            ep.SetMemoryEPD(block._epd+IDX_MAGIC1,ep.SetTo,_magic()[1]),
            ep.SetMemoryEPD(block._epd+IDX_VERSION,ep.SetTo,PROTOCOL_VERSION),
            ep.SetMemoryEPD(block._epd+IDX_SELF_PTR,ep.SetTo,_ptr(block._epd)),
            ep.SetMemoryEPD(block._epd+IDX_SIZE,ep.SetTo,SIZE),
        ])
    ep.EUDOnStart(_start)
    _CONFIGURED=True
    return _DESCRIPTOR


def _required():
    if not _CONFIGURED or _DESCRIPTOR is None:
        raise RuntimeError("Call SCSaver.configure() first")


def clear_bindings():
    global _FLAT
    if _LOCKED:
        raise RuntimeError("SCSaver bindings are locked")
    del _BINDINGS[:]
    _KEYS.clear()
    _FLAT=[]


def bind_array(key, values, count):
    global _FLAT
    _required()
    if _LOCKED:
        raise RuntimeError("SCSaver.bind_array() must be called before tick/save/load")
    key=str(key).strip(); count=int(count)
    if not key:
        raise RuntimeError("SCSaver binding key must not be empty")
    if key in _KEYS:
        raise RuntimeError("SCSaver duplicated binding key: %s" % key)
    if count < 1:
        raise RuntimeError("SCSaver binding count must be at least 1")
    if len(_FLAT)+count > MAX_VALUES:
        raise RuntimeError("SCSaver registered values exceed %d" % MAX_VALUES)
    if not hasattr(values, "_epd"):
        raise RuntimeError("SCSaver.bind_array() requires EUDArray-like values")
    start=len(_FLAT)
    _BINDINGS.append((key,values,count,start)); _KEYS.add(key)
    for index in range(count):
        _FLAT.append((values,index))
    return start


def bind_value(key, value_array):
    return bind_array(key, value_array, 1)


def binding_count(): return len(_BINDINGS)
def value_count(): return len(_FLAT)
def chunk_count(): return (len(_FLAT)+CHUNK_CAPACITY-1)//CHUNK_CAPACITY


def _lock():
    global _LOCKED
    _LOCKED=True
    if not _FLAT:
        raise RuntimeError("SCSaver has no bindings")


def _pack_save_chunk():
    for chunk in range(chunk_count()):
        start=chunk*CHUNK_CAPACITY
        part=_FLAT[start:start+CHUNK_CAPACITY]
        if ep.EUDIf()(_LOCAL_CHUNK[0].Exactly(chunk)):
            for offset,(values,index) in enumerate(part):
                _DESCRIPTOR[IDX_PAYLOAD0+offset]=values[index]
            _DESCRIPTOR[IDX_CHUNK_INDEX]=chunk
            _DESCRIPTOR[IDX_CHUNK_SIZE]=len(part)
        ep.EUDEndIf()


def _stage_load_chunk():
    for chunk in range(chunk_count()):
        start=chunk*CHUNK_CAPACITY
        part=_FLAT[start:start+CHUNK_CAPACITY]
        if ep.EUDIf()(_LOCAL_CHUNK[0].Exactly(chunk)):
            for offset in range(len(part)):
                _LOCAL_PACKET[PACKET_HEADER+start+offset]=_DESCRIPTOR[IDX_PAYLOAD0+offset]
        ep.EUDEndIf()


def _set_metadata():
    _DESCRIPTOR[IDX_SLOT]=_LOCAL_SLOT[0]
    _DESCRIPTOR[IDX_TOTAL_COUNT]=len(_FLAT)
    _DESCRIPTOR[IDX_CHUNK_COUNT]=chunk_count()
    _DESCRIPTOR[IDX_PAYLOAD_COUNT]=_DESCRIPTOR[IDX_CHUNK_SIZE]
    _DESCRIPTOR[IDX_RESULT]=0xFFFFFFFF
    _DESCRIPTOR[IDX_ERROR]=0


def _make_result_packet(status, count):
    _LOCAL_PACKET[0]=status
    _LOCAL_PACKET[1]=count
    _LOCAL_PACKET_LENGTH[0]=count+PACKET_HEADER
    _LOCAL_PACKET_READY[0]=1


@ep.EUDFunc
def tick_local():
    """Process launcher memory locally. Never apply gameplay data here."""
    _required(); _lock()
    ep.RawTrigger(actions=[
        ep.SetMemoryEPD(_DESCRIPTOR._epd+IDX_MAGIC0,ep.SetTo,_magic()[0]),
        ep.SetMemoryEPD(_DESCRIPTOR._epd+IDX_MAGIC1,ep.SetTo,_magic()[1]),
        ep.SetMemoryEPD(_DESCRIPTOR._epd+IDX_MAP_HB,ep.Add,1),
    ])

    hb=ep.EUDVariable(); status=ep.EUDVariable()
    hb << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_LAUNCHER_HB)
    status << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_LAUNCHER_STATUS)
    if ep.EUDIfNot()(hb.Exactly(_LAST_LAUNCHER_HB[0])):
        _LAST_LAUNCHER_HB[0]=hb; _STALE[0]=0
        if ep.EUDIf()(status.Exactly(ONLINE)):
            _CONNECTED[0]=1
        if ep.EUDElse()():
            _CONNECTED[0]=0
        ep.EUDEndIf()
    if ep.EUDElse()():
        if ep.EUDIf()(_STALE[0] < TIMEOUT):
            _STALE[0]+=1
        ep.EUDEndIf()
        if ep.EUDIf()(_STALE[0].AtLeast(TIMEOUT)):
            _CONNECTED[0]=0
        ep.EUDEndIf()
    ep.EUDEndIf()

    save_ack=ep.EUDVariable(); load_ack=ep.EUDVariable()
    result=ep.EUDVariable(); error=ep.EUDVariable()
    save_ack << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_SAVE_ACK)
    load_ack << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_LOAD_ACK)
    result << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_RESULT)
    error << ep.f_dwread_epd(_DESCRIPTOR._epd+IDX_ERROR)

    if ep.EUDIfNot()(save_ack.Exactly(_LAST_SAVE_ACK[0])):
        _LAST_SAVE_ACK[0]=save_ack
        if ep.EUDIf()(_LOCAL_MODE[0].Exactly(1)):
            if ep.EUDIf()(result.Exactly(0)):
                if chunk_count() > 1:
                    if ep.EUDIf()(_LOCAL_CHUNK[0] < chunk_count()-1):
                        _LOCAL_CHUNK[0]+=1
                        _pack_save_chunk(); _set_metadata(); _DESCRIPTOR[IDX_SAVE_REQ]+=1
                    if ep.EUDElse()():
                        _LOCAL_MODE[0]=0
                        _make_result_packet(1,0)
                    ep.EUDEndIf()
                else:
                    _LOCAL_MODE[0]=0
                    _make_result_packet(1,0)
            if ep.EUDElse()():
                _LOCAL_MODE[0]=0
                _make_result_packet(0x80000000+error,0)
            ep.EUDEndIf()
        ep.EUDEndIf()
    ep.EUDEndIf()

    if ep.EUDIfNot()(load_ack.Exactly(_LAST_LOAD_ACK[0])):
        _LAST_LOAD_ACK[0]=load_ack
        if ep.EUDIf()(_LOCAL_MODE[0].Exactly(2)):
            if ep.EUDIf()(result.Exactly(0)):
                _stage_load_chunk()
                if chunk_count() > 1:
                    if ep.EUDIf()(_LOCAL_CHUNK[0] < chunk_count()-1):
                        _LOCAL_CHUNK[0]+=1
                        _DESCRIPTOR[IDX_CHUNK_INDEX]=_LOCAL_CHUNK[0]
                        _DESCRIPTOR[IDX_CHUNK_SIZE]=0
                        _set_metadata(); _DESCRIPTOR[IDX_LOAD_REQ]+=1
                    if ep.EUDElse()():
                        _LOCAL_MODE[0]=0
                        _make_result_packet(1,len(_FLAT))
                    ep.EUDEndIf()
                else:
                    _LOCAL_MODE[0]=0
                    _make_result_packet(1,len(_FLAT))
            if ep.EUDElse()():
                _LOCAL_MODE[0]=0
                _make_result_packet(0x80000000+error,0)
            ep.EUDEndIf()
        ep.EUDEndIf()
    ep.EUDEndIf()


@ep.EUDFunc
def begin_local_save(player, slot):
    _required()
    _lock()

    if ep.EUDIf()(
        _CONNECTED[0].Exactly(0)
    ):
        _make_result_packet(
            0x80000001,
            0,
        )

        ep.EUDReturn(0)

    ep.EUDEndIf()

    if ep.EUDIf()(
        _LOCAL_MODE[0].Exactly(0)
    ):
        _LOCAL_PACKET_READY[0] = 0

        _LOCAL_PLAYER[0] = player
        _LOCAL_SLOT[0] = slot
        _LOCAL_CHUNK[0] = 0
        _LOCAL_MODE[0] = 1
        _LOCAL_PROGRESS_TIMER[0] = 11
        _pack_save_chunk()
        _set_metadata()

        _DESCRIPTOR[
            IDX_SAVE_REQ
        ] += 1

        # 첫 번째 저장 페이지 표시
        _print_save_progress(
            _LOCAL_PLAYER[0]
        )

        ep.EUDReturn(1)

    ep.EUDEndIf()

    ep.EUDReturn(0)

@ep.EUDFunc
def begin_local_load(player, slot):
    _required()
    _lock()

    if ep.EUDIf()(
        _CONNECTED[0].Exactly(0)
    ):
        _make_result_packet(
            0x80000001,
            0,
        )

        ep.EUDReturn(0)

    ep.EUDEndIf()

    if ep.EUDIf()(
        _LOCAL_MODE[0].Exactly(0)
    ):
        _LOCAL_PACKET_READY[0] = 0

        _LOCAL_PLAYER[0] = player
        _LOCAL_SLOT[0] = slot
        _LOCAL_CHUNK[0] = 0
        _LOCAL_MODE[0] = 2
        _LOCAL_PROGRESS_TIMER[0] = 11
        _DESCRIPTOR[
            IDX_CHUNK_INDEX
        ] = 0

        _DESCRIPTOR[
            IDX_CHUNK_SIZE
        ] = 0

        _set_metadata()

        _DESCRIPTOR[
            IDX_LOAD_REQ
        ] += 1

        # 첫 번째 로드 페이지 표시
        _print_load_progress(
            _LOCAL_PLAYER[0]
        )

        ep.EUDReturn(1)

    ep.EUDEndIf()

    ep.EUDReturn(0)

@ep.EUDFunc
def take_local_packet():
    """Return packet length once; call only in the requester local branch."""
    if ep.EUDIf()(_LOCAL_PACKET_READY[0].Exactly(1)):
        _LOCAL_PACKET_READY[0]=0
        ep.EUDReturn(_LOCAL_PACKET_LENGTH[0])
    ep.EUDEndIf()
    ep.EUDReturn(0)


@ep.EUDFunc
def local_connected(): return _CONNECTED[0]
@ep.EUDFunc
def shared_busy(): return _SHARED_BUSY[0]


@ep.EUDFunc
def set_shared_busy(value):
    _SHARED_BUSY[0]=value

SAVE_START_TEXT = "\x07[SCSaver] \x04데이터를 저장하는 중입니다."
LOAD_START_TEXT = "\x07[SCSaver] \x04데이터를 불러오는 중입니다."
@ep.EUDFunc
def play_request_sound(player, operation):
    # This function is called from the synchronized StartRequest branch.
    if ep.EUDIf()(operation.Exactly(2)):
            _notify_player(
                player,
                LOAD_START_TEXT,
                LOAD_START_WAV,
                True,
            )
    ep.EUDEndIf()

    if ep.EUDIf()(operation.Exactly(1)):
            _notify_player(
                player,
                SAVE_START_TEXT,
                LOAD_START_WAV,
                True,
            )
    ep.EUDEndIf()


@ep.EUDFunc
def complete_shared_packet(packet_epd, operation, player):
    """Apply only an MSQC-verified packet in a synchronized branch."""
    status=ep.EUDVariable(); count=ep.EUDVariable()
    status << ep.f_dwread_epd(packet_epd)
    count << ep.f_dwread_epd(packet_epd+1)

    if ep.EUDIf()(status.Exactly(1)):
        if ep.EUDIf()(operation.Exactly(2)):
            if ep.EUDIfNot()(count.Exactly(len(_FLAT))):
                _FAIL_EVENT[0]=1; _LAST_ERROR[0]=5; _SHARED_BUSY[0]=0
                _notify_player(player, ERROR_TEXT, OPERATION_ERROR_WAV)
                ep.EUDReturn(0)
            ep.EUDEndIf()
            for index,(values,value_index) in enumerate(_FLAT):
                values[value_index]=ep.f_dwread_epd(packet_epd+PACKET_HEADER+index)
            _LOAD_EVENT[0]=1
        if ep.EUDElse()():
            _SAVE_EVENT[0]=1
        ep.EUDEndIf()
        _SHARED_BUSY[0]=0
        if ep.EUDIf()(operation.Exactly(2)):
            _notify_player(player, LOAD_DONE_TEXT, OPERATION_DONE_WAV)
        if ep.EUDElse()():
            _notify_player(player, SAVE_DONE_TEXT, OPERATION_DONE_WAV)
        ep.EUDEndIf()
        ep.EUDReturn(1)
    ep.EUDEndIf()

    _FAIL_EVENT[0]=1
    _LAST_ERROR[0]=status-0x80000000
    _SHARED_BUSY[0]=0
    _notify_player(player, ERROR_TEXT, OPERATION_ERROR_WAV)
    ep.EUDReturn(0)


@ep.EUDFunc
def abort_shared(error_code, player):
    _SHARED_BUSY[0]=0
    _FAIL_EVENT[0]=1
    _LAST_ERROR[0]=error_code
    _notify_player(player, ERROR_TEXT, OPERATION_ERROR_WAV)


@ep.EUDFunc
def save_completed():
    if ep.EUDIf()(_SAVE_EVENT[0].Exactly(1)):
        _SAVE_EVENT[0]=0; ep.EUDReturn(1)
    ep.EUDEndIf(); ep.EUDReturn(0)


@ep.EUDFunc
def load_completed():
    if ep.EUDIf()(_LOAD_EVENT[0].Exactly(1)):
        _LOAD_EVENT[0]=0; ep.EUDReturn(1)
    ep.EUDEndIf(); ep.EUDReturn(0)


@ep.EUDFunc
def failed():
    if ep.EUDIf()(_FAIL_EVENT[0].Exactly(1)):
        _FAIL_EVENT[0]=0; ep.EUDReturn(1)
    ep.EUDEndIf(); ep.EUDReturn(0)


@ep.EUDFunc
def error_code(): return _LAST_ERROR[0]


def local_packet_epd(): return _LOCAL_PACKET._epd

setup=configure
f_tick=tick_local
