# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

[English](README.md) | **한국어**

TOML 설정 파일의 값을 파이썬에서 고치되, 사용자가 써 둔 주석과 서식은 그대로 두는 패키지.
바뀌는 줄만 다시 쓰므로 손으로 단 주석, 빈 줄, 정렬한 `=`이 편집 뒤에도 남습니다.

## 1. 설치

```sh
pip install tomlite
```

의존성 없음. Python 3.11 이상. Windows·macOS·Linux에서 동작합니다.

## 2. 빠른 시작

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")                      # 파일 읽기, 없으면 빈 문서

# "bob" 사용자가 아직 없을 때만 [[user]] 블록 추가
if not doc.has_in_array("user", match_field="name", match_value="bob"):
    doc.append_to_array("user", [("name", "bob"), ("role", "guest")])

doc.set_root_key("title", "My App", only_if_absent=True)  # title이 없을 때만 설정 (있으면 그대로)
doc.set_table_key("server", "debug", False)               # [server]의 debug를 false로 변경
doc.save("config.toml")                                   # 주석·서식을 유지하며 디스크에 다시 쓰기
```

값은 `tomllib`로 읽습니다:

```python
import tomllib

with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

## 3. 지원 형식

프로그램이 관리하는 설정 파일이 쓰는 세 가지 형식을 편집합니다:

```toml
title = "My App"                 # 최상위 키

[server]                         # 테이블
host = "localhost"
port = 8080
debug = true
tags = ["web", "prod"]           # 값: str, int, float, bool, 문자열 배열

[[user]]                         # 테이블 배열, 필드로 항목을 찾음
name = "alice"
role = "admin"
```

중첩 테이블, 인라인 테이블, 배열의 배열, 점으로 이어진 키, 다중행 문자열이 있으면 편집하지
않고 `UnsupportedTOMLError`를 냅니다. 읽기와 `dumps`는 그대로 됩니다.

## 4. Round-trip

값에 따옴표, 대괄호, 백슬래시 같은 특수문자가 들어 있어도 tomlite가 안전하게 저장하고 그대로
다시 읽습니다. 값을 바꿔도 그 줄에 달린 주석은 남고, 여러 줄로 쓴 배열은 여러 줄로 유지되며,
줄바꿈 방식(LF·CRLF)도 원본 그대로 유지됩니다.

## 5. API

| 메서드 | 설명 |
|---|---|
| `TOMLEditor.load(path)` | 파일 읽기, 없으면 빈 문서. |
| `TOMLEditor.loads(text)` | TOML 문자열에서 문서 생성. |
| `.dumps()` → `str` | 문서를 텍스트로. |
| `.save(path)` | 원자적 쓰기, 기존 파일 모드 유지. |
| `.set_root_key(key, value, *, only_if_absent=False, multiline=False)` | 최상위 키 설정. `only_if_absent`는 값이 있으면 건너뜀. |
| `.unset_root_key(key)` → `bool` | 최상위 키 제거. |
| `.has_in_array(array, *, match_field, match_value)` → `bool` | `[[array]]` 블록에 `match_field = match_value`가 있는지. |
| `.append_to_array(array, fields, *, before_table=None, multiline=False)` | `[[array]]` 블록 추가, 필요하면 특정 테이블 앞에. |
| `.update_in_array(array, *, match_field, match_value, field, value, multiline=False)` → `bool` | 찾은 블록에서 `field` 설정. |
| `.remove_from_array(array, *, match_field, match_value)` → `bool` | 찾은 블록 제거. |
| `.set_table_key(table, key, value, *, multiline=False)` | `[table]`에 `key` 설정, 없으면 테이블 생성. |
| `.unset_table_key(table, key)` → `bool` | `[table]`에서 `key` 제거. |

값은 `str`, `int`, `float`, `bool`, `str` 시퀀스 중 하나입니다. match 인자는 키워드 전용입니다.
`multiline=True`는 배열 값을 한 줄에 하나씩 씁니다. 여러 줄인 배열을 비어 있지 않은 배열로 바꾸면 여러 줄로 유지됩니다.

## 6. 라이선스

[MIT](LICENSE)
