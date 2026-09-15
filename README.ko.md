# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

코드에서 TOML 설정 파일을 고치되 **사용자가 써둔 주석과 서식을 지우지 않습니다.**
`tomlite`는 파일을 줄 단위로 제자리 편집합니다 — 바뀌는 줄만 건드리므로, 손으로 단
`# 메모`, 빈 줄, 정렬해둔 `=` 열이 편집 후에도 그대로 남습니다.

TOML 읽기는 표준 라이브러리(`tomllib`)가 이미 해결합니다. `tomlite`는 나머지 절반 —
쓰기 — 을 작고 의존성 없이 담당합니다.

[English](README.md) | **한국어**

```python
from tomlite import TOMLDocument

doc = TOMLDocument.load("config.toml")
doc.set_table_key("contacts", "lead", "lead@example.com")
doc.save("config.toml")
```

## `tomlkit`이 있는데 왜?

[tomlkit](https://pypi.org/project/tomlkit/)은 서식까지 보존하는 완전한 TOML 라이브러리로,
문서 전체를 트리로 모델링해 어떤 TOML도 표현합니다. `tomlite`는 일부러 더 작습니다:

- **읽기는 `tomllib`, 쓰기는 `tomlite`.** 파서는 이미 표준 라이브러리에 있습니다.
  `tomlite`는 표준 라이브러리가 안 하는 것 — 주석을 보존하는 *쓰기* — 만 합니다.
- **의존성 0**, 순수 Python, 작은 모듈 하나.
- TOML 전 문법이 아니라, **프로그램이 관리하는 설정 파일이 실제로 취하는 좁은 형태**
  (최상위 키 몇 개, `[[테이블 배열]]`, flat `[테이블]`)에 맞춘 안전한 표면.

임의의 TOML(중첩 테이블, 인라인 테이블, 배열의 배열, 점표기 트리)을 다뤄야 하면
`tomlkit`을, 자기 설정에 계정이나 피드를 추가하면서 사용자 주석은 건드리고 싶지 않은
CLI라면 `tomlite`가 더 알맞습니다.

## 설치

```sh
pip install tomlite
```

다른 건 아무것도 끌어오지 않습니다. Python 3.11 이상.

## 무엇을 편집하나

`tomlite`는 세 가지 형태 — 프로그램이 관리하는 설정 파일이 쓰는 것 — 를 이해합니다:

```toml
default_account = "personal"     # 최상위 키

[[accounts]]                     # 테이블 배열: 필드로 항목을 찾음
email = "you@naver.com"
alias = "personal"

[contacts]                       # flat 테이블
lead = "lead@example.com"
team = ["lead", "boss"]          # 값: 문자열, 정수, 불리언, 또는 한 줄 문자열 배열
```

## API

`TOMLDocument`은 줄로 들고 있는 파일입니다. 불러오고, 편집하고, 저장합니다.

| 메서드 | 하는 일 |
|---|---|
| `TOMLDocument.load(path)` | 파일 읽기(없으면 빈 문서). |
| `TOMLDocument.loads(text)` | TOML 문자열에서 문서 생성. |
| `.dumps()` → `str` | 문서를 텍스트로. |
| `.save(path)` | 원자적 쓰기, 기존 파일 모드 보존. |
| `.set_root_key(name, value, *, only_if_absent=False)` | 최상위 키 설정. `only_if_absent`는 기본값을 덮어쓰지 않고 심음. |
| `.has_in_array(array, *, field, value)` → `bool` | `[[array]]` 블록에 `field = value`가 있는지. |
| `.append_to_array(array, fields, *, before_table=None)` | `[[array]]` 블록 추가, 선택적으로 특정 테이블 앞에. |
| `.update_in_array(array, *, match_field, match_value, field, value)` → `bool` | `match_field = match_value`인 블록에서 `field` 설정. |
| `.set_table_key(table, key, value)` | `[table]`에 `key` 설정, 테이블 없으면 생성. |

값은 `str`, `int`, `bool`, 또는 `str` 시퀀스(한 줄 배열로 기록). match/field 인자는
키워드 전용입니다 — 같은 타입 문자열이 줄지어 있으면 순서를 바꿔 유효하지만 잘못된
호출을 하기 쉬워서입니다.

## Round-trip 보장

`tomlite`는 **자신이 써낸 것은 무엇이든 round-trip**합니다. 대괄호·등호·따옴표·백슬래시·
제어문자·이국적 줄바꿈이 들어간 값이나 키도 완전한 이스케이프로 기록되고 그대로 다시
읽히므로, 나중 편집에서 파일을 깨뜨리지 않습니다. 항목을 갱신하면 그 줄의 인라인 주석도
유지되고, 다른 줄은 바이트 그대로 남습니다.

계약 밖은 `tomlite`가 애초에 *쓰지 않는* 값입니다: 중첩 배열, 인라인 테이블, 또는 스칼라
한 줄 배열이 아닌 다중행 값. 이런 걸 손으로 써놓고 `tomlite`로 편집하면 편집이 깔끔히
반영된다고 보장하지 않습니다. 임의의 TOML은 `tomlkit`을 쓰세요.

## 라이선스

MIT
