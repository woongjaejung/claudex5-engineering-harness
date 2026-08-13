# Claudex5 Engineering Harness 한국어 사용 안내

## 핵심만 먼저

이 프로젝트의 핵심은 Claude Code와 Codex의 **전역 지침 및 전역 에이전트 설정**입니다. 따라서 특정 작업에서만 수동 호출하는 일반 스킬과 달리, 설치 후 어느 프로젝트에서든 평소처럼 `claude` 또는 `codex`를 실행하고 자연어로 요청하면 적용됩니다.

다만 Superpowers와 함께 사용할 때만 로드되는 작은 호환 어댑터 스킬 `claudex5-subagent-routing`도 설치합니다. 이 스킬은 하네스 전체를 스킬로 바꾸는 것이 아니라, Superpowers가 실행 절차를 맡는 동안 Claudex5가 역할과 모델 선택을 유지하게 연결합니다.

```bash
cd 작업할-프로젝트
claude
```

```text
이 기능을 구현하고 테스트해줘. 기존 API 호환성은 유지해줘.
```

작은 요청은 메인 Claude가 바로 처리합니다. 여러 파일에 걸치거나 모호하고 위험한 작업은 자동으로 조사, 구현, 독립 검토, 결정적 검증 단계로 확장됩니다. 여기서 결정적 검증은 다른 AI의 의견이 아니라 build, lint, typecheck, test 명령의 실제 성공 여부를 뜻합니다.

## Superpowers와 함께 사용할 때

둘의 책임은 다음처럼 나뉩니다.

- Superpowers: 계획, 작업공간(worktree), 작업 원장, 태스크 반복, 체크포인트, 리뷰 게이트
- Claudex5: 조사자·구현자·리뷰어·판정자와 각 모델 선택, Spark 조건부 사용, 최종 실제 테스트

Superpowers가 `subagent-driven-development` 또는 `executing-plans`를 선택하면 전역 지침이 `claudex5-subagent-routing`을 자동으로 로드합니다. 사용자는 평소처럼 “1번 방식으로 오케스트레이션해줘”라고 말하면 되고, 실행 방식을 두 번 고를 필요가 없습니다.

`fable-advisor`처럼 자체 구현 lane과 모델 선택표를 가진 다른 오케스트레이션 플러그인이 켜져 있으면 Claudex5 라우팅을 대신할 수 있습니다. 이 경우 Superpowers는 그대로 두고 경쟁 라우터만 비활성화하는 것을 권장합니다.

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
./install.sh
./verify.sh --strict
```

Claude와 ChatGPT 로그인은 각 머신에서 한 번씩 직접 해야 합니다. 다른 컴퓨터의 인증 파일은 새 컴퓨터나 서버로 복사되지 않습니다.
인증 뒤 `./install.sh`를 한 번 더 실행하는 이유는 계정별 Spark 접근 가능 여부를 그때 처음 정확히 확인할 수 있기 때문입니다.

## Pro 계정의 Spark 자동 사용

Spark의 정확한 모델 식별자는 `gpt-5.3-codex-spark`입니다. 현재 연구 프리뷰에서는 ChatGPT Pro 계정에만 제공되지만, 하네스는 인증 파일에서 구독 이름을 읽거나 추측하지 않습니다. 대신 Codex의 공식 `model/list` 기능으로 현재 계정에 이 모델이 실제 표시되는지만 확인합니다.

- Spark가 표시되면 `harness_spark_ui_iteration` 전역 역할을 자동 등록합니다.
- Spark가 없거나 확인에 실패하면 설치는 정상 완료되고 Sonnet 구현 역할을 사용합니다.
- 확인 과정에서는 모델에게 프롬프트를 보내지 않으므로 Spark 사용량을 소비하지 않습니다.
- 모델 목록, 구독 정보, 토큰은 파일에 저장하거나 Git에 포함하지 않습니다.

Spark가 자동 배정되는 범위는 기존 화면의 작고 명확한 수정 한 가지입니다. 예를 들면 간격, 문구, 버튼 상태 또는 좁은 시각적 오류를 고치고 브라우저로 확인하는 작업입니다. 백엔드 로직, 구조 설계, 보안 기능, 데이터 마이그레이션, 큰 리팩터링과 코드 리뷰에는 사용하지 않습니다.

평소처럼 다음과 같이 요청하면 됩니다.

```text
기존 설정 창에서 저장 버튼 위 간격만 다른 입력 영역과 맞춰줘.
동작과 데이터 흐름은 바꾸지 말고 브라우저에서 확인해줘.
```

Spark가 등록된 머신에서 명시적으로 호출하려면 Claude Code 안에서 다음처럼 요청할 수 있습니다.

```text
/codex:rescue --fresh --model spark 기존 프로필 카드의 간격 한 곳만 수정하고 동작은 유지한 채 브라우저에서 검증해줘.
```

Codex에서는 다음처럼 역할을 직접 지정할 수 있습니다.

```text
harness_spark_ui_iteration 역할로 기존 UI의 이 한 가지 변경만 처리해줘.
```

`~/.codex/agents/harness-spark-ui-iteration.toml` 링크가 없다면 Spark를 강제로 호출하지 않습니다. 로그인이나 구독 상태가 바뀐 뒤 `./install.sh`를 다시 실행하면 자동으로 재확인합니다.

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
- 접근 가능할 때만 작은 기존 UI 수정에 Spark 사용, 불가능하면 Sonnet으로 자동 전환
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

로컬 PC에서 이 대화에서 만든 기본 경로를 사용한다면:

```bash
cd ~/Documents/github/claudex5-engineering-harness
git pull --ff-only origin main
./install.sh
./verify.sh --strict
```

VPS 또는 다른 서버에서는 실제로 복제한 경로로 이동해서 같은 순서로 실행합니다. 예를 들어 홈 디렉터리에 복제했다면:

```bash
cd ~/claudex5-engineering-harness
git pull --ff-only origin main
./install.sh
./verify.sh --strict
```

`git pull`은 공개 설정 파일을 업데이트하고, `./install.sh`는 해당 머신의 현재 계정으로 Spark 접근 여부를 다시 확인한 뒤 전역 지침과 역할을 안전하게 병합합니다. 인증은 머신별로 그대로 유지되며 다른 장비로 복사되지 않습니다.

## 제거

```bash
./uninstall.sh
```

사용자 지침과 기존 설정은 남기고, 이 저장소가 관리하는 링크·지침 블록·Codex 역할 표만 제거합니다. Claude, Codex, 로그인과 플러그인은 삭제하지 않습니다.
조건부 Spark 링크와 역할 표도 하네스가 만든 경우에만 함께 제거합니다.

## 문제 해결

설치 상태 확인:

```bash
./verify.sh
```

`fable-advisor`가 Claudex5 역할 대신 Grok 또는 자체 Codex lane을 호출할 때:

```bash
claude plugin list
claude plugin disable fable-advisor@fable-advisor
./install.sh
./verify.sh --strict
```

목록에서 `Scope: project` 또는 `Scope: local`로 표시되면 해당 범위를 정확히 붙입니다.

```bash
claude plugin disable fable-advisor@fable-advisor --scope project
```

그 뒤 실행 중인 Claude Code 세션을 종료하고 다시 시작합니다. Superpowers는 비활성화하지 않으며, `./verify.sh --strict`는 `fable-advisor`가 계속 활성화되어 있으면 실패로 알려줍니다. 하네스는 기존 플러그인을 자동으로 끄지 않습니다.

특정 작업에서 의도적으로 `fable-advisor`를 쓰고 싶다면 그 작업 프롬프트에 플러그인 이름을 정확히 명시하면 됩니다. 그 명시적 선택은 현재 작업에 한해 Claudex5 기본 라우팅보다 우선합니다.

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

Spark 상태가 현재 계정과 맞지 않는다는 경고가 나오면 다음을 실행합니다.

```bash
codex login status
./install.sh
./verify.sh
```

일시적인 네트워크 또는 인증 확인 실패는 설치 실패로 처리하지 않습니다. 그동안 Sonnet 대체 경로가 유지되며, 접근이 복구된 뒤 설치를 다시 실행하면 Spark 역할이 활성화됩니다.

전체 구조, 백업 복구, 보안 경계와 기여 방법은 루트 [README](../README.md)를 참고하세요.
