# Claudex5 Engineering Harness 한국어 사용 안내

## 핵심만 먼저

이 프로젝트는 스킬이 아니라 Claude Code와 Codex의 **전역 지침 및 전역 에이전트 설정**입니다. 설치 후에는 어느 프로젝트에서든 평소처럼 `claude` 또는 `codex`를 실행하고 자연어로 요청하면 됩니다.

```bash
cd 작업할-프로젝트
claude
```

```text
이 기능을 구현하고 테스트해줘. 기존 API 호환성은 유지해줘.
```

작은 요청은 메인 Claude가 바로 처리합니다. 여러 파일에 걸치거나 모호하고 위험한 작업은 자동으로 조사, 구현, 독립 검토, 결정적 검증 단계로 확장됩니다. 여기서 결정적 검증은 다른 AI의 의견이 아니라 build, lint, typecheck, test 명령의 실제 성공 여부를 뜻합니다.

## 설치

이미 Claude Code와 Codex가 설치된 컴퓨터 또는 서버:

```bash
git clone https://github.com/woongjaejung/claudex5-engineering-harness.git
cd claudex5-engineering-harness
./install.sh
./verify.sh --strict
```

새 Debian/Ubuntu 컴퓨터 또는 서버:

```bash
git clone https://github.com/woongjaejung/claudex5-engineering-harness.git
cd claudex5-engineering-harness
./install.sh --bootstrap
claude
codex login --device-auth
./verify.sh --strict
```

Claude와 ChatGPT 로그인은 각 머신에서 한 번씩 직접 해야 합니다. 다른 컴퓨터의 인증 파일은 새 컴퓨터나 서버로 복사되지 않습니다.

## 자연스럽게 자동 오케스트레이션시키는 프롬프트

역할 이름을 외울 필요는 없습니다. 목표, 지켜야 할 조건, 확인하고 싶은 위험을 평소 말투로 알려주는 것이 가장 좋습니다.

```text
사용자 초대 기능을 구현해줘. 기존 가입 흐름은 깨지면 안 되고,
권한 상승과 중복 초대 문제도 검토해줘. 테스트 결과까지 알려줘.
```

```text
이 간헐적 장애의 원인을 찾아서 가장 작은 수정으로 고쳐줘.
재현 근거와 수정 전후 검증 결과를 함께 보여줘.
```

이런 표현은 전역 지침이 다음을 판단하는 데 도움을 줍니다.

- 먼저 읽기 전용 조사가 필요한가
- 구현 범위가 명확한가
- 독립 Codex 분석이 정확도를 높이는가
- 구조 검토나 공격적 검토가 필요한가
- 완료 전에 어떤 실제 테스트를 실행해야 하는가

## 역할을 직접 지정할 때

Claude 오케스트레이터를 메인 세션으로 강제 실행:

```bash
claude --agent harness-orchestrator
```

세션 안에서 특정 Claude 역할을 요청:

```text
harness-researcher로 이 저장소의 인증 흐름만 읽기 전용 조사해줘.
```

```text
harness-architecture-reviewer로 현재 변경의 모듈 경계와 롤백 위험을 검토해줘.
```

Claude Code 안에서 Codex를 새 맥락으로 호출:

```text
/codex:rescue --fresh --model gpt-5.6-sol --effort high 이 문제의 원인과 대안을 독립 조사해줘
/codex:review --background
/codex:adversarial-review --background 인증 우회와 데이터 손실 가능성을 공격적으로 검토해줘
/codex:status
/codex:result
```

현재 공식 플러그인 1.0.0은 추론 수준을 `xhigh`까지만 받습니다. 정확한 Luna Max가 필요하면 신뢰하는 프로젝트 폴더에서 Codex를 직접 실행합니다.

```bash
codex exec --ephemeral --model gpt-5.6-luna \
  -c 'model_reasoning_effort="max"' \
  --sandbox workspace-write \
  "지정한 파일과 완료 조건 안에서만 대안 구현하고 지정한 테스트를 실행해줘."
```

조사나 리뷰처럼 파일을 바꾸면 안 되는 작업은 `--sandbox read-only`를 사용합니다. 플러그인의 `xhigh` 실행을 `max`라고 보고하지 않습니다.

## 자동 동작과 수동 fallback

자동으로 맡기는 항목:

- 작업 규모와 위험도 분류
- 필요한 경우 Sonnet 조사·구현 역할 호출
- 의미 있는 변경에 대한 독립 검토
- build, lint, typecheck, test 실행
- 서브에이전트 결과의 실제 파일 대조

수동 선택을 남기는 항목:

- Fable 오케스트레이터 또는 판정자가 unavailable일 때 Opus 전환
- Sonnet 구현이 근거와 함께 막혔을 때 Opus 구현 승격
- 범위가 애매한 상태에서 Luna에게 구현을 맡기는 결정
- 기존 신뢰 설정을 바꾸는 `--harden`
- 새 머신의 Claude/ChatGPT 로그인

수동 대체 역할:

```bash
claude --agent harness-orchestrator-opus
claude --agent harness-implementer-opus
claude --agent harness-judge-opus
```

## 업데이트

```bash
cd claudex5-engineering-harness
git pull --ff-only
./install.sh
./verify.sh --strict
```

## 제거

```bash
./uninstall.sh
```

사용자 지침과 기존 설정은 남기고, 이 저장소가 관리하는 링크·지침 블록·Codex 역할 표만 제거합니다. Claude, Codex, 로그인과 플러그인은 삭제하지 않습니다.

## 문제 해결

설치 상태 확인:

```bash
./verify.sh
```

플러그인 명령이 보이지 않을 때 Claude Code 안에서 실행:

```text
/reload-plugins
/codex:setup
```

컴퓨터 또는 서버에 인증이 없을 때:

```bash
claude
codex login --device-auth
```

모델을 사용할 수 없을 때는 `/model`에서 사용 가능한 Claude 모델을 확인하고 위 Opus 대체 역할을 수동으로 선택합니다. 저장소 경로를 옮겨 링크가 끊어졌다면 출력된 `harness-*` 심볼릭 링크만 확인해 제거한 뒤 새 위치에서 `./install.sh`를 다시 실행합니다.

전체 구조, 백업 복구, 보안 경계와 기여 방법은 루트 [README](../README.md)를 참고하세요.
