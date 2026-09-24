# SCSaver

스타크래프트 리마스터 EUD 맵을 위한 **로컬 저장 및 불러오기 시스템**입니다.

맵의 `EUDArray` 데이터를 전용 런처를 통해 암호화 파일로 저장하고, 멀티플레이에서는 MSQC를 이용해 요청 플레이어의 데이터를 모든 클라이언트에 동기화한 뒤 동일하게 적용합니다.

> 현재 기준 개발 환경
>
> - euddraft `0.10.2.5`
> - EUD Editor 3 `0.19.6.0`
> - Windows 10/11
> - StarCraft: Remastered

## 주요 기능

- 최대 **4,096개 값** 등록
- 청크당 **64개 값** 저장 및 로드
- 여러 슬롯 지원
- AES-GCM 기반 로컬 저장 파일 보호
- Windows DPAPI 기반 자동 로그인 정보 보호
- P1부터 P8까지 요청 플레이어별 로컬 저장 파일 사용
- MSQC 20채널을 통한 멀티플레이 데이터 동기화
- 수신 데이터 검증 및 오류 데이터 재전송
- 멀티플레이 저장 및 로드 시 디싱크 방지
- 요청 플레이어 한정 문구 및 스타크래프트 내장 사운드 출력
- 런처 단일 실행 제한
- 실행별 로그 파일 및 `latestlog.txt` 생성

## 동작 구조

```text
공유 조건에서 저장 또는 로드 요청
        ↓
요청 플레이어의 PC만 로컬 런처와 통신
        ↓
런처 결과를 로컬 패킷에 저장
        ↓
MSQC 20채널로 모든 클라이언트에 전송
        ↓
수신 데이터 검증 및 필요한 데이터 재전송
        ↓
모든 클라이언트가 동일한 패킷 확보
        ↓
공유 조건에서 실제 EUDArray에 적용
        ↓
저장 또는 로드 완료 이벤트 발생
```

런처의 로컬 ACK는 공유 게임 데이터를 직접 변경하지 않습니다. 실제 데이터 적용은 MSQC 검증이 완료된 이후에만 수행됩니다.

## 프로젝트 구성

```text
SCSaver/
├─ plugins/
│  └─ scsaver.py
├─ TriggerEditor/
│  ├─ scsaversync.eps
│  └─ msqcloader.eps
├─ launcher/
│  └─ SCSaverLauncher.py
├─ examples/
│  └─ SCSaverExample.eps
└─ README.md
```

## 설치

### 1. Python 플러그인 설치

`scsaver.py`를 euddraft 플러그인 폴더에 복사합니다.

```text
euddraft0.10.2.5\plugins\scsaver.py
```

### 2. epScript 모듈 설치

다음 파일을 맵 프로젝트에 복사합니다.

```text
맵 프로젝트/
├─ scsaversync.eps
├─ msqcloader.eps
└─ main.eps
```

### 3. EDS에 MSQC 채널 등록

빌드에 사용하는 `.eds` 파일에 다음 설정을 추가합니다.

```ini
[MSQC]
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend1 : MSQCReceive1
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend2 : MSQCReceive2
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend3 : MSQCReceive3
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend4 : MSQCReceive4
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend5 : MSQCReceive5
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend6 : MSQCReceive6
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend7 : MSQCReceive7
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend8 : MSQCReceive8
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend9 : MSQCReceive9
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend10 : MSQCReceive10
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend11 : MSQCReceive11
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend12 : MSQCReceive12
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend13 : MSQCReceive13
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend14 : MSQCReceive14
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend15 : MSQCReceive15
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend16 : MSQCReceive16
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend17 : MSQCReceive17
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend18 : MSQCReceive18
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend19 : MSQCReceive19
MSQCIsTransfer.Exactly(1) ; xy , MSQCSend20 : MSQCReceive20
```

## 빠른 시작

```javascript
import scsaversync as Sync;

const SCSaver = py_eval('__import__("SCSaver")');
const SaveData = EUDArray(3);

var RequestState = 0;

function onPluginStart() {
    SCSaver.configure("MyMapStableId", 1);
    SCSaver.bind_array("SaveData", SaveData, 3);

    foreach (i : EUDLoopRange(3)) {
        SaveData[i] = 2;
    }

    Sync.Init();
}

function beforeTriggerExec() {
    // 내부에서 런처 통신과 MSQC 전송을 처리합니다.
    // 다른 위치에서 SCSaver.tick_local()을 중복 호출하지 마세요.
    Sync.Exec();

    if (RequestState == 1 && Sync.SaveCompleted()) {
        RequestState = 0;
    }

    if (RequestState == 2 && Sync.LoadCompleted()) {
        RequestState = 0;
    }

    if (Sync.Failed()) {
        RequestState = 0;
        eprintAll("\x08SCSaver 오류: {}", Sync.ErrorCode());
    }
}

function afterTriggerExec() {
    if (Sync.Save(P1, 0)) {
        RequestState = 1;
    }

    if (Sync.Load(P1, 0)) {
        RequestState = 2;
    }
}
```

## API

### `SCSaver.configure(map_id, schema_version)`

저장 파일에서 맵과 데이터 구조를 구분할 고정 ID를 설정합니다.

```javascript
SCSaver.configure("MyMapStableId", 1);
```

`map_id`는 출력 맵 파일명이 아니라 업데이트 후에도 유지할 고유 문자열을 권장합니다.

### `SCSaver.bind_array(key, array, count)`

`EUDArray`의 값을 저장 대상으로 등록합니다.

```javascript
SCSaver.bind_array("PlayerData", PlayerData, 128);
```

### `SCSaver.bind_value(key, value_array)`

길이가 1인 배열을 단일 값으로 등록합니다.

```javascript
SCSaver.bind_value("Stage", StageValue);
```

### `Sync.Save(player, slot)`

해당 플레이어의 로컬 런처를 사용해 지정한 슬롯에 저장합니다.

```javascript
Sync.Save(P2, 0);
```

### `Sync.Load(player, slot)`

해당 플레이어의 로컬 저장 파일을 읽어 MSQC로 공유한 뒤 모든 클라이언트에 동일하게 적용합니다.

```javascript
Sync.Load(P2, 0);
```

### 이벤트 및 상태

```javascript
Sync.IsBusy();
Sync.SaveCompleted();
Sync.LoadCompleted();
Sync.Failed();
Sync.ErrorCode();
```

완료 및 실패 이벤트는 한 번 읽으면 초기화되는 1회성 이벤트입니다.

## 멀티플레이 사용 규칙

### 공유 조건에서 요청하기

안전한 조건 예시:

```javascript
Bring(...)
Switch(...)
Deaths(...)
MSQC로 생성된 공유 명령
```

로컬 키 입력을 직접 사용하지 마세요.

```javascript
// 멀티플레이에서는 직접 사용하지 않는 것을 권장합니다.
if (@KeyDown(P1, "INSERT")) {
    Sync.Save(P1, 0);
}
```

로컬 입력이 필요하다면 MSQC로 먼저 공유 데스값 또는 스위치로 변환한 뒤 SCSaver 요청을 실행해야 합니다.

### 한 번에 요청 하나

MSQC 전송 채널 충돌을 막기 위해 한 번에 하나의 저장 또는 로드만 처리합니다.

```text
P1 로드 중
→ P2 저장 요청 대기
→ P1 로드 완료
→ 다음 요청 허용
```

### 동일한 맵 사용

모든 참가자는 동일한 최종 빌드 맵을 사용해야 합니다. 서로 다른 버전의 맵을 사용하면 디싱크가 발생할 수 있습니다.

## 청크 처리

```text
청크당 값: 64개
최대 등록값: 4,096개
```

예를 들어 130개 값을 등록하면 다음과 같이 처리됩니다.

```text
Page 1: 64개
Page 2: 64개
Page 3: 2개
```

## 알림

기본 알림은 요청 플레이어에게만 출력됩니다.

```text
저장 시작
저장 완료
로드 시작
로드 완료
오류
```

스타크래프트 기본 사운드를 사용하므로 별도 음원 삽입이 필요하지 않습니다.

```text
sound\Misc\swishin.wav
sound\Misc\TDrTra01.wav
sound\glue\Buzz.wav
```

맵 EPS에서 동일한 `PlayWAV()`나 완료 문구를 다시 출력하면 중복될 수 있습니다.

## 런처 데이터

### 저장 파일

```text
런처 폴더/data/SCSaver.scsave
```

저장 파일은 인증 암호화를 사용합니다. 파일이 손상되거나 암호문이 임의로 변경되면 인증에 실패하여 로드가 거부됩니다.

### 자동 로그인

```text
%LOCALAPPDATA%\SCSaver\auth.dat
```

자동 로그인 정보는 Windows 사용자 계정에 연결된 DPAPI 방식으로 보호됩니다.

### 로그

```text
%LOCALAPPDATA%\SCSaver\log\
├─ YYYY-MM-DD_HH-MM-SS.log
└─ latestlog.txt
```

정상 종료 시 현재 세션 로그가 `latestlog.txt`로 복사됩니다. 비정상 종료 시에는 날짜가 가장 최근인 `.log` 파일을 확인하세요.

비밀번호, 암호화 키, 복호화된 저장 데이터는 로그에 기록하지 않습니다.

## 오류 코드

- `1`: 요청 플레이어의 런처가 연결되지 않음
- `2`: 런처 저장 또는 로드 오류
- `3`: 잘못된 슬롯
- `4`: MSQC 전송 타임아웃
- `5`: 동기화된 데이터 개수 불일치

## 성능 및 APM

MSQC는 Queue Command를 데이터 전송 채널로 사용하므로 저장과 로드 중 스타크래프트 APM이 순간적으로 높게 표시될 수 있습니다.

```text
전송 중 APM 상승
→ 전송 완료
→ 추가 상승 중단
```

완료 후에도 APM이 계속 증가한다면 저장 또는 로드 요청이 반복 실행되고 있는지 확인하세요.

## 보안 범위

SCSaver는 일반적인 파일 손상과 단순 바이트 변조를 탐지하도록 설계되었습니다. 로컬 저장 방식이므로 운영 서버 기반의 계정 검증이나 서버 서명을 제공하지는 않습니다.

## 테스트 권장 절차

1. 두 개 이상의 실제 클라이언트에서 동일한 맵을 실행합니다.
2. 각 클라이언트에서 런처를 실행합니다.
3. 테스트 값을 설정하고 요청 플레이어로 저장합니다.
4. 값을 초기화합니다.
5. 같은 플레이어의 슬롯을 로드합니다.
6. 모든 클라이언트의 값이 동일한지 확인합니다.
7. 방갈림 또는 강제 종료가 없는지 확인합니다.
8. 리방 후 같은 슬롯을 다시 로드합니다.
9. 런처 재실행 후 자동 로그인과 로드를 확인합니다.
10. 로그 파일 생성 여부를 확인합니다.

## 문제 해결

### 오류 코드 4

EDS에 MSQC 20채널 설정이 모두 등록되었는지 확인합니다.

```text
MSQCIsTransfer
MSQCSend1 ~ MSQCSend20
MSQCReceive1 ~ MSQCReceive20
```

### 맵 빌드 시 인자 개수 오류

`scsaver.py`와 `scsaversync.eps`가 같은 릴리스의 파일인지 확인하세요. 서로 다른 버전의 2인자 및 3인자 API 파일을 섞으면 컴파일 오류가 발생할 수 있습니다.

### 저장 또는 로드가 무한 반복됨

`LocalRequestStarted` 래치가 포함된 `scsaversync.eps`를 사용하고 있는지 확인하세요.

### 진행 문구가 중복됨

맵 EPS의 별도 문구 출력과 `PlayWAV()`를 제거하세요. 플러그인이 요청 플레이어에게 알림을 자동 출력할 수 있습니다.

## 제한사항

- Windows 전용 런처
- 한 번에 하나의 저장 또는 로드 요청만 처리
- MSQC 전송 중 순간 APM 상승 가능
- 등록된 값은 공유 게임 상태로 모든 클라이언트에 동일하게 적용
- 맵 업데이트에서 `map_id` 또는 스키마를 변경하면 기존 저장과 호환되지 않을 수 있음

## 기여

문제 제보 시 다음 정보를 포함해 주세요.

- euddraft 버전
- EUD Editor 버전
- 사용한 SCSaver 릴리스
- 참가 플레이어 수
- 오류 코드
- 재현 절차
- `%LOCALAPPDATA%\SCSaver\log\latestlog.txt`
- 강제 종료였다면 가장 최근 날짜의 `.log` 파일
