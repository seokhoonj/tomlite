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
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")
doc.set_table_key("contacts", "lead", "lead@example.com")
doc.save("config.toml")
```

## 언제 알맞나

`tomlite`는 일부러 작습니다. 이럴 때 맞습니다:

- **프로그램이 관리하는 설정 파일에 항목 몇 개를 추가·변경·삭제**하면서 사용자의 주석과
  서식은 그대로 두고 싶을 때.
- **읽기는 이미 해결돼 있음.** 표준 라이브러리가 TOML을 파싱하고(`tomllib`), `tomlite`는
  안 하는 것 — 주석 보존 *쓰기* — 만 합니다.
- **파일이 평평한 형태**일 때: 최상위 키 몇 개, `[[테이블 배열]]`, flat `[테이블]`,
  값은 문자열·숫자·불리언·한 줄 배열.

범용 TOML 조작 라이브러리는 아닙니다. 그 형태 밖(중첩 테이블, 인라인 테이블, 배열의 배열,
점표기 트리)은 계약 밖이며, 그런 건 완전한 TOML 라이브러리를 쓰세요.

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

`TOMLEditor`은 줄로 들고 있는 파일입니다. 불러오고, 편집하고, 저장합니다.

| 메서드 | 하는 일 |
|---|---|
| `TOMLEditor.load(path)` | 파일 읽기(없으면 빈 문서). |
| `TOMLEditor.loads(text)` | TOML 문자열에서 문서 생성. |
| `.dumps()` → `str` | 문서를 텍스트로. |
| `.save(path)` | 원자적 쓰기, 기존 파일 모드 보존. |
| `.set_root_key(key, value, *, only_if_absent=False)` | 최상위 키 설정. `only_if_absent`는 기본값을 덮어쓰지 않고 심음. |
| `.unset_root_key(key)` → `bool` | 최상위 키 제거. |
| `.has_in_array(array, *, match_field, match_value)` → `bool` | `[[array]]` 블록에 `match_field = match_value`가 있는지. |
| `.append_to_array(array, fields, *, before_table=None)` | `[[array]]` 블록 추가, 선택적으로 특정 테이블 앞에. |
| `.update_in_array(array, *, match_field, match_value, field, value)` → `bool` | `match_field = match_value`인 블록에서 `field` 설정. |
| `.remove_from_array(array, *, match_field, match_value)` → `bool` | `match_field = match_value`인 블록 제거. |
| `.set_table_key(table, key, value)` | `[table]`에 `key` 설정, 테이블 없으면 생성. |
| `.unset_table_key(table, key)` → `bool` | `[table]`에서 `key` 제거. |

값은 `str`, `int`, `float`, `bool`, 또는 `str` 시퀀스(한 줄 배열로 기록). 못 찾을 수 있는
메서드는 `bool`을, 순수 setter는 `None`을 반환합니다. match 인자는 키워드 전용입니다 —
같은 타입 문자열이 줄지어 있으면 순서를 바꿔 유효하지만 잘못된 호출을 하기 쉬워서입니다.

## Round-trip 보장

`tomlite`는 **자신이 써낸 것은 무엇이든 round-trip**합니다. 대괄호·등호·따옴표·백슬래시·
제어문자·이국적 줄바꿈이 들어간 값이나 키도 완전한 이스케이프로 기록되고 그대로 다시
읽히므로, 나중 편집에서 파일을 깨뜨리지 않습니다. 항목을 갱신하면 그 줄의 인라인 주석도
유지되고, 다른 줄의 내용은 그대로입니다(불러올 때 줄바꿈을 LF로 정규화하므로, CRLF 파일은
내용이 아니라 줄바꿈만 바뀝니다).

계약 밖은 `tomlite`가 애초에 *쓰지 않는* 값입니다: 중첩 배열, 인라인 테이블, 또는 스칼라
한 줄 배열이 아닌 다중행 값. 특히 **다중행 문자열(`"""…"""` / `'''…'''`)이 든 파일을
편집하려 하면 조용히 손상시키지 않고 `UnsupportedTOMLError`로 거부**합니다(읽기·`dumps`는
그대로 됨). 임의의 TOML은 완전한 TOML 라이브러리를 쓰세요.

## 라이선스

MIT
