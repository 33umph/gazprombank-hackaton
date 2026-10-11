from __future__ import annotations
from logger import log_event


import os
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
import re


import re
from dataclasses import dataclass, field


class SQLGuardError(ValueError):
    pass


@dataclass(frozen=True)
# настройки проверки sql
class GuardConfig:
    allowed_tables: frozenset = frozenset({"ФАКУЛЬТЕТЫ", "ПРЕПОДОВАТЕЛИ", "ПРЕДМЕТЫ"})


    aggregate_only_tables: frozenset = frozenset()
    max_rows: int = 50

    pii_substrings: tuple = ("паспорт", "телефон", "phone", "passport", "email", "e_mail",
                             "почт", "адрес", "address", "дата_рожд", "рожден", "birth")
    pii_exact: tuple = ("инн", "снилс", "inn", "snils")

    identifying_substrings: tuple = ()


@dataclass
class Tok:
    kind: str
    value: str
    start: int
    end: int
    raw: str = ""


_WORD = re.compile(r"[^\W\d]\w*", re.UNICODE)
_NUM = re.compile(r"\d+(?:\.\d+)?|\.\d+")


# разбор sql на токены
def tokenize(sql: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i) or sql.startswith("/*", i):
            raise SQLGuardError("Комментарии в SQL запрещены")
        elif c in "'\"":
            j = i + 1
            while True:
                if j >= n:
                    raise SQLGuardError("Незакрытая кавычка в SQL")
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            body = sql[i + 1:j].replace(c * 2, c)
            if c == "'" and toks and toks[-1].kind == "word" and toks[-1].end == i\
                    and toks[-1].value in ("E", "U", "B", "X", "N"):
                raise SQLGuardError("Префиксные строковые литералы (E'', U&'') запрещены")
            toks.append(Tok("str" if c == "'" else "qident", body, i, j + 1, sql[i:j + 1]))
            i = j + 1
        elif c in "$\\":
            raise SQLGuardError("Символы '$' и '\\' в SQL запрещены")
        elif c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            m = _NUM.match(sql, i)
            toks.append(Tok("num", m.group(0), i, m.end(), m.group(0)))
            i = m.end()
        elif c.isalpha() or c == "_":
            m = _WORD.match(sql, i)
            toks.append(Tok("word", m.group(0).upper(), i, m.end(), m.group(0)))
            i = m.end()
        else:
            toks.append(Tok("punct", c, i, i + 1, c))
            i += 1
    return toks


# достаём select из ответа модели
def extract_select(raw: str) -> str:
    text = re.sub(r"```[a-zA-Z]*", " ", raw or "")
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            j = i + 1
            while j < n:
                if text[j] == c:
                    if j + 1 < n and text[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("--", i):
            k = text.find("\n", i)
            i = n if k == -1 else k
        elif text.startswith("/*", i):
            k = text.find("*/", i + 2)
            i = n if k == -1 else k + 2
        elif c == ";":
            break
        else:
            out.append(c)
            i += 1
    cleaned = "".join(out)
    m = re.search(r"\bSELECT\b", cleaned, re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned[m.start():]).strip() if m else ""


# запрещённые слова и разрешённые функции
FORBIDDEN_WORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE",
    "COPY", "INTO", "EXECUTE", "CALL", "DO", "SET", "RESET", "VACUUM", "ANALYZE", "LOCK",
    "LISTEN", "NOTIFY", "PREPARE", "DEALLOCATE", "DECLARE", "FETCH", "SHARE", "COMMIT",
    "ROLLBACK", "BEGIN", "SAVEPOINT", "REFRESH", "REINDEX", "CLUSTER", "COMMENT", "IMPORT",
    "WITH", "RETURNING", "MERGE", "LATERAL",
    "CURRENT_USER", "SESSION_USER", "USER", "CURRENT_CATALOG", "CURRENT_SCHEMA", "CURRENT_ROLE",
}
ALLOWED_FUNCS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "CEIL", "CEILING", "FLOOR", "ABS",
    "COALESCE", "NULLIF", "GREATEST", "LEAST", "LOWER", "UPPER", "LENGTH", "TRIM", "SUBSTRING",
    "LEFT", "RIGHT", "CONCAT", "EXTRACT", "DATE_TRUNC", "TO_CHAR", "CAST", "STRING_AGG",
    "ARRAY_AGG", "NOW", "ROW_NUMBER", "RANK", "DENSE_RANK", "VARCHAR", "NUMERIC", "DECIMAL",
    "CHAR", "TEXT", "INTEGER", "INT", "BIGINT", "DATE", "FLOAT",
}
AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "STRING_AGG", "ARRAY_AGG"}

KW_BEFORE_PAREN = {
    "IN", "EXISTS", "ANY", "ALL", "SOME", "AND", "OR", "NOT", "ON", "USING", "AS", "SELECT",
    "WHERE", "OVER", "FILTER", "LIKE", "ILIKE", "BETWEEN", "WHEN", "THEN", "ELSE", "FROM",
    "JOIN", "UNION", "INTERSECT", "EXCEPT", "BY", "HAVING", "LIMIT", "OFFSET", "DISTINCT",
    "CASE", "IS", "SIMILAR", "TO", "PARTITION", "WITHIN", "INNER", "OUTER", "CROSS", "FULL",
}
NOT_ALIAS = {
    "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT", "EXCEPT", "ON",
    "USING", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "WINDOW", "OUTER",
}
FROM_IN_FUNC = {"EXTRACT", "SUBSTRING", "TRIM", "OVERLAY", "POSITION"}
CLAUSE_STOP = {"GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT", "EXCEPT"}


@dataclass
class ValidatedQuery:
    sql: str
    tables: list = field(default_factory=list)
    joins: list = field(default_factory=list)
    aggregates: list = field(default_factory=list)
    where: str | None = None
    limit: int = 0
    limit_added: bool = False
    limit_clamped: bool = False

    def explain(self) -> dict:
        return {
            "tables": self.tables,
            "joins": self.joins,
            "filters": self.where,
            "aggregates": self.aggregates,
            "restrictions": (["SELECT-only (read-only транзакция)", f"LIMIT {self.limit}"]
                             + (["LIMIT добавлен автоматически"] if self.limit_added else [])
                             + (["LIMIT уменьшен до допустимого"] if self.limit_clamped else [])),
        }


def is_pii_name(name: str, cfg: GuardConfig) -> bool:
    low = name.lower()
    return low in cfg.pii_exact or any(s in low for s in cfg.pii_substrings)


def _is_identifying(name: str, cfg: GuardConfig) -> bool:
    low = name.lower()
    return any(s in low for s in cfg.identifying_substrings)


def safe_columns(columns: list[str], cfg: GuardConfig = GuardConfig()) -> list[int]:
    return [i for i, c in enumerate(columns) if not is_pii_name(str(c), cfg)]


# основная проверка запроса
def validate(sql: str, cfg: GuardConfig = GuardConfig()) -> ValidatedQuery:
    if not sql or not sql.strip():
        raise SQLGuardError("Пустой SQL-запрос")
    toks = tokenize(sql)


    if toks and toks[-1].kind == "punct" and toks[-1].value == ";":
        toks = toks[:-1]
    if any(t.kind == "punct" and t.value == ";" for t in toks):
        raise SQLGuardError("Разрешён только один SQL-оператор")
    if not toks or toks[0].kind != "word" or toks[0].value != "SELECT":
        raise SQLGuardError("Разрешены только запросы SELECT")

    def peek(k: int) -> Tok | None:
        return toks[k] if 0 <= k < len(toks) else None

    tables: list[str] = []
    joins: list[str] = []
    aggs: list[str] = []
    stack: list[str] = []
    where_start = where_end = None
    limit_idx = None

    for i, t in enumerate(toks):
        prev, nxt = peek(i - 1), peek(i + 1)
        depth = len(stack)

        if t.kind == "punct":
            if t.value == "(":
                stack.append(prev.value if prev and prev.kind == "word" else "")
            elif t.value == ")":
                if not stack:
                    raise SQLGuardError("Несбалансированные скобки")
                stack.pop()
            elif t.value == "*" and prev is not None:

                star_in_select = (prev.kind == "word" and prev.value in ("SELECT", "DISTINCT"))\
                    or (prev.kind == "punct" and prev.value in (",", "."))
                if star_in_select and (not stack or stack[-1] not in AGGREGATES)\
                        and set(tables_used_later(toks, cfg)) & set(cfg.aggregate_only_tables):
                    raise SQLGuardError("SELECT * запрещён для таблиц со студентами/абитуриентами — "
                                        "используйте агрегаты (COUNT, AVG ...)")
            continue

        if t.kind == "str" or t.kind == "num":
            continue

        name = t.value if t.kind == "qident" else t.raw

        if is_pii_name(name, cfg):
            raise SQLGuardError("Доступ к персональным данным заблокирован")
        if name.lower().startswith("pg_") or name.lower() == "information_schema":
            raise SQLGuardError("Обращение к системным объектам PostgreSQL запрещено")
        if t.kind == "qident":
            if nxt and nxt.kind == "punct" and nxt.value == "(":
                raise SQLGuardError("Недопустимый вызов функции")
            continue


        w = t.value
        if w in FORBIDDEN_WORDS:
            raise SQLGuardError(f"Ключевое слово {w} запрещено (разрешён только SELECT)")


        if nxt and nxt.kind == "punct" and nxt.value == "(" and w not in KW_BEFORE_PAREN:
            if w not in ALLOWED_FUNCS:
                raise SQLGuardError(f"Функция {t.raw}() не разрешена")
            if w in AGGREGATES:
                aggs.append(w)

        if w == "WHERE" and not stack and where_start is None:
            where_start = t.end
        if depth == 0 and w in CLAUSE_STOP and where_start is not None and where_end is None:
            where_end = t.start
        if w == "LIMIT" and depth == 0:
            limit_idx = i


        if w in ("FROM", "JOIN"):
            if w == "FROM" and ((stack and stack[-1] in FROM_IN_FUNC)
                                or (prev and prev.kind == "word" and prev.value == "DISTINCT")):
                continue
            found = _table_refs(toks, i + 1, is_from=(w == "FROM"), cfg=cfg)
            for tb in found:
                if tb not in tables:
                    tables.append(tb)
                if w == "JOIN" and tb not in joins:
                    joins.append(tb)

    if stack:
        raise SQLGuardError("Несбалансированные скобки")
    if not tables:
        raise SQLGuardError("В запросе нет обращения к таблицам из белого списка")


    agg_tables = [tb for tb in tables if tb in cfg.aggregate_only_tables]
    if agg_tables:
        if not aggs:
            raise SQLGuardError(f"Данные таблицы «{agg_tables[0]}» доступны только в агрегированном виде")
        for t in toks:
            if t.kind in ("word", "qident"):
                nm = t.value if t.kind == "qident" else t.raw
                if _is_identifying(nm, cfg):
                    raise SQLGuardError("Нельзя выводить данные, идентифицирующие студентов/абитуриентов")


    out_sql = sql.strip().rstrip(";").rstrip()
    limit_added = limit_clamped = False
    if limit_idx is not None:
        num = peek(limit_idx + 1)
        if not num or num.kind != "num" or not num.value.isdigit():
            raise SQLGuardError("LIMIT должен быть целым числом")
        limit = int(num.value)
        if limit > cfg.max_rows:
            out_sql = out_sql[:num.start] + str(cfg.max_rows) + out_sql[num.end:]
            limit, limit_clamped = cfg.max_rows, True
    else:
        out_sql += f" LIMIT {cfg.max_rows}"
        limit, limit_added = cfg.max_rows, True

    where = sql[where_start:where_end].strip() if where_start is not None else None
    return ValidatedQuery(out_sql, tables, joins, sorted(set(aggs)), where, limit, limit_added, limit_clamped)


def tables_used_later(toks: list[Tok], cfg: GuardConfig) -> list[str]:
    res = []
    for i, t in enumerate(toks):
        if t.kind == "word" and t.value in ("FROM", "JOIN"):
            for tb in _table_refs(toks, i + 1, is_from=(t.value == "FROM"), cfg=cfg, strict=False):
                res.append(tb)
    return res


def _table_refs(toks: list[Tok], i: int, is_from: bool, cfg: GuardConfig, strict: bool = True) -> list[str]:
    found: list[str] = []

    def at(k):
        return toks[k] if 0 <= k < len(toks) else None

    while True:
        t = at(i)
        if t is None:
            raise SQLGuardError("Ожидалось имя таблицы после FROM/JOIN")
        if t.kind == "punct" and t.value == "(":
            return found
        if t.kind not in ("word", "qident"):
            raise SQLGuardError("Ожидалось имя таблицы после FROM/JOIN")
        n1 = at(i + 1)
        if n1 and n1.kind == "punct" and n1.value == "(":
            raise SQLGuardError("Функции в FROM запрещены")
        if n1 and n1.kind == "punct" and n1.value == ".":
            if t.value.lower() != "public":
                raise SQLGuardError("Обращение к другим схемам запрещено")
            i += 2
            t = at(i)
            if t is None or t.kind not in ("word", "qident"):
                raise SQLGuardError("Ожидалось имя таблицы после схемы")
        if t.kind != "qident" or t.value not in cfg.allowed_tables:
            if strict:
                shown = t.raw if t.kind == "qident" else t.raw
                hint = " (имена таблиц нужно писать в двойных кавычках, точно как в схеме)"\
                    if t.kind == "word" and t.raw.upper() in {x.upper() for x in cfg.allowed_tables} else ""
                raise SQLGuardError(f"Таблица {shown} не входит в список разрешённых{hint}")
        else:
            found.append(t.value)
        i += 1
        a = at(i)
        if a and a.kind == "word" and a.value == "AS":
            i += 2
        elif a and (a.kind == "qident" or (a.kind == "word" and a.value not in NOT_ALIAS)):
            i += 1
        a = at(i)
        if is_from and a and a.kind == "punct" and a.value == ",":
            i += 1
            continue
        return found


import decimal
import json
import logging
import threading
import time
from collections import defaultdict, deque

import requests
from requests.adapters import HTTPAdapter
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sqlalchemy import create_engine, text

# сервер
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app, origins=os.getenv("ALLOWED_ORIGINS", "*").split(","))


DANEK_IP = os.getenv("DB_HOST", '100.88.169.106')
DB_USER = os.getenv("DB_USER", 'postgres')
DB_NAME = os.getenv("DB_NAME", 'postgres')
DB_PORT = os.getenv("DB_PORT", '5432')

DB_PASS = os.getenv("DB_PASS") or input("Пароль БД PostgreSQL: ").strip()

DB_TIMEOUT_MS = int(os.getenv("DB_TIMEOUT_MS", "5000"))
DB_URI = f'postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DANEK_IP}:{DB_PORT}/{DB_NAME}'
engine = create_engine(
    DB_URI, pool_size=5, max_overflow=10, pool_pre_ping=True,

    connect_args={'connect_timeout': 5,
                  'options': f'-c statement_timeout={DB_TIMEOUT_MS} -c default_transaction_read_only=on'})

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:3b")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "2"))
LLM_MAX_QUEUE = int(os.getenv("LLM_MAX_QUEUE", "8"))
LLM_QUEUE_TIMEOUT = float(os.getenv("LLM_QUEUE_TIMEOUT", "45"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
MAX_QUESTION_LEN = 500

CFG = GuardConfig(
    allowed_tables=frozenset({"ФАКУЛЬТЕТЫ", "ПРЕПОДОВАТЕЛИ", "ПРЕДМЕТЫ", "СТУДЕНТЫ", "АБИТУРИЕНТЫ"}),
    aggregate_only_tables=frozenset(),
    max_rows=int(os.getenv("MAX_ROWS", "50")),
)

# промпт для модели
SYSTEM_PROMPT = """You are a SQL generator for PostgreSQL (university database).
Output EXACTLY ONE query starting with SELECT. No markdown, no comments, no explanations.
If the question cannot be answered with this schema (weather, jokes, personal data, changing data) output only: NO_SQL

DATABASE SCHEMA (use ONLY these tables and columns, NEVER invent others):
- "ФАКУЛЬТЕТЫ" ("id_факультета", "Название_факультета", "Сокращение", "Декан")
- "ПРЕПОДОВАТЕЛИ" ("id_преподавателя", "Фамилия", "id_факультета", "Кафедра", "Должность", "Учёная_степень")
- "СТУДЕНТЫ" ("id_студента", "Фамилия", "Группа", "id_факультета", "Год_поступления", "Форма_обучения")
- "ПРЕДМЕТЫ" ("id_предмета", "Название_предмета", "id_преподавателя", "id_факультета", "Семестр", "Часы")
- "АБИТУРИЕНТЫ" ("id_заявления", "Фамилия", "id_факультета", "Направление", "Год", "Баллы")

RULES:
0. The dean is the column "Декан" in "ФАКУЛЬТЕТЫ" (there is NO table of deans).
1. Wrap table and column names in double quotes.
2. STUDENTS and APPLICANTS: Individual records and names (e.g. "Фамилия") MAY be listed when requested.
3. ALWAYS USE % WILDCARDS IN ILIKE PATTERNS AND WORD STEMS, never exact forms and never "=" for names:
   - "машинного обучения" -> '%машин%обуч%', "информационных технологий" -> '%информац%технолог%'.
   - For education form search using ILIKE '%платн%' or ILIKE '%бюджет%'.
   - For positions search ILIKE '%доцент%', '%профессор%'.
4. FACULTY FILTERING:
   - When filtering by faculty, JOIN "ФАКУЛЬТЕТЫ" f ON table."id_факультета" = f."id_факультета".
   - Always search both columns: (f."Сокращение" ILIKE '%term%' OR f."Название_факультета" ILIKE '%term%').
5. Teacher + subject together: JOIN "ПРЕПОДОВАТЕЛИ" p and "ПРЕДМЕТЫ" sub ON p."id_преподавателя" = sub."id_преподавателя".
6. AGGREGATION ALIASES:
   - For "количество" / "сколько": COUNT(*) AS "Количество".
   - For "сумма" / "часов": SUM("Часы") AS "Сумма_часов" or SUM(...) AS "Сумма".
   - For "среднее": AVG(...) AS "Среднее".

EXAMPLES:
User: количество студентов на ФИТ
SQL: SELECT COUNT(*) AS "Количество" FROM "СТУДЕНТЫ" s JOIN "ФАКУЛЬТЕТЫ" f ON s."id_факультета" = f."id_факультета" WHERE f."Сокращение" ILIKE '%ФИТ%' OR f."Название_факультета" ILIKE '%ФИТ%';

User: студенты ФИТ
SQL: SELECT s."Фамилия", s."Группа" FROM "СТУДЕНТЫ" s JOIN "ФАКУЛЬТЕТЫ" f ON s."id_факультета" = f."id_факультета" WHERE f."Сокращение" ILIKE '%ФИТ%' OR f."Название_факультета" ILIKE '%ФИТ%';

User: количество студентов на платном обучении
SQL: SELECT COUNT(*) AS "Количество" FROM "СТУДЕНТЫ" WHERE "Форма_обучения" ILIKE '%платн%';

User: сколько всего часов по предметам
SQL: SELECT SUM("Часы") AS "Сумма_часов" FROM "ПРЕДМЕТЫ";

User: кто декан факультета информационных технологий
SQL: SELECT "Декан" FROM "ФАКУЛЬТЕТЫ" WHERE "Название_факультета" ILIKE '%информац%технолог%' OR "Сокращение" ILIKE '%ФИТ%';

User: преподаватели машинного обучения
SQL: SELECT DISTINCT p."Фамилия", p."Кафедра" FROM "ПРЕПОДОВАТЕЛИ" p JOIN "ПРЕДМЕТЫ" sub ON p."id_преподавателя" = sub."id_преподавателя" WHERE sub."Название_предмета" ILIKE '%машин%обуч%';

User: средний балл абитуриентов на ФИТ в 2026 году
SQL: SELECT AVG(a."Баллы") AS "Среднее" FROM "АБИТУРИЕНТЫ" a JOIN "ФАКУЛЬТЕТЫ" f ON a."id_факультета" = f."id_факультета" WHERE (f."Сокращение" ILIKE '%ФИТ%' OR f."Название_факультета" ILIKE '%ФИТ%') AND a."Год" = 2026;

User: как менялся набор студентов за последние пять лет
SQL: SELECT "Год_поступления", COUNT(*) AS "Количество" FROM "СТУДЕНТЫ" WHERE "Год_поступления" >= EXTRACT(YEAR FROM NOW()) - 4 GROUP BY "Год_поступления" ORDER BY "Год_поступления";

User: сколько заявлений подано на Экономику в 2026 году
SQL: SELECT COUNT(*) AS "Количество" FROM "АБИТУРИЕНТЫ" WHERE "Направление" ILIKE '%эконом%' AND "Год" = 2026;

User: какая погода в Москве
SQL: NO_SQL
"""


class LLMError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class NoSQL(Exception):
    pass


def mask_pii(cols, rows):
    keep = safe_columns([str(c) for c in cols], CFG)
    return [cols[i] for i in keep], [[r[i] for i in keep] for r in rows]


def sanitize_stem_in_sql(sql: str) -> str:
    def stem_replacer(match):
        word = match.group(1)
        if len(word) <= 4 or word.isupper():
            return f"ILIKE '%{word}%'"

        trimmed = re.sub(r'(ова|ева|ина|ом|ем|ой|ами|ям|а|у|е|ы|и)$', '', word, flags=re.IGNORECASE)
        if len(trimmed) >= 3:
            return f"ILIKE '%{trimmed}%'"
        return match.group(0)

    return re.sub(r"ILIKE\s+'%([^%'\s]+)%'", stem_replacer, sql, flags=re.IGNORECASE)


_http = requests.Session()
_http.mount('http://', HTTPAdapter(pool_connections=4, pool_maxsize=16))
_llm_slots = threading.Semaphore(LLM_CONCURRENCY)
_waiting = 0
_waiting_lock = threading.Lock()


# очередь к ollama
def _call_ollama(payload: dict) -> str:
    global _waiting
    with _waiting_lock:
        if _waiting >= LLM_MAX_QUEUE:
            raise LLMError("Сервер перегружен, повторите запрос через несколько секунд.")
        _waiting += 1
    try:
        got = _llm_slots.acquire(timeout=LLM_QUEUE_TIMEOUT)
    finally:
        with _waiting_lock:
            _waiting -= 1
    if not got:
        raise LLMError("Сервер перегружен, повторите запрос через несколько секунд.")
    try:
        res = _http.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
        res.raise_for_status()
        return res.json().get("response", "").strip()
    except Exception as e:
        print(f"[ERROR] Ollama request failed: {e}")
        raise LLMError("Языковая модель сейчас недоступна. Попробуйте позже.") from e
    finally:
        _llm_slots.release()


def generate_sql(question: str, feedback: str = None) -> str:
    prompt = f"{SYSTEM_PROMPT}\n\nUser: {question}\nSQL:"
    if feedback:
        prompt += f" (предыдущий вариант отклонён: {feedback}. Исправь и выведи один новый SELECT.)\nSQL:"
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.0,
            "num_predict": 300,
            "stop": ["User:", "Question:", ";\n"]
        }
    }
    raw_sql = _call_ollama(payload)
    clean = extract_select(raw_sql)
    if not clean:
        raise NoSQL()
    return sanitize_stem_in_sql(clean)


def validate_sql(sql: str, question: str):
    q_lower = question.lower()
    pii_keywords = ["паспорт", "телефон", "номер телефона", "паспортные", "адрес", "почта", "email", "снилс"]
    if any(kw in q_lower for kw in pii_keywords):
        raise SQLGuardError("Запрос заблокирован: политика информационной безопасности запрещает доступ к персональным контактам и документам.")
    return validate(sql, CFG)


# запрос в read-only транзакции
def run_select(sql: str):
    with engine.begin() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(DB_TIMEOUT_MS)}"))
        res = conn.execute(text(sql.replace(":", r"\:")))
        return [str(c) for c in res.keys()], [list(r) for r in res.fetchall()]


FAST_HOURS = re.compile(r"(сколько всего часов|сумма часов|суммарно часов|всего часов)( по предметам)?")
FAST_HOURS_SQL = 'SELECT SUM("Часы") AS "Сумма_часов" FROM "ПРЕДМЕТЫ"'

_sql_cache: dict = {}
_cache_lock = threading.Lock()


def _cache_put(key, vq, max_size=500):
    with _cache_lock:
        if len(_sql_cache) >= max_size:
            _sql_cache.pop(next(iter(_sql_cache)))
        _sql_cache[key] = vq


_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
        return False


def _reject(ip, question, message, code):
    log_event(event="reject", ip=ip, question=question, status=code, error=message)
    return jsonify({'success': False, 'error': message}), code


def _answer(cols, rows, truncated, limit):
    if not rows:
        return "По вашему запросу данные не найдены."
    if len(rows) == 1 and len(cols) == 1:
        return f"{cols[0]}: {rows[0][0]}"
    msg = f"Найдено строк: {len(rows)}."
    return msg + (f" Показаны первые {limit}." if truncated else "")


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


AGG_NAMES = {'count': 'Количество', 'sum': 'Сумма', 'avg': 'Среднее', 'min': 'Минимум', 'max': 'Максимум'}


def _json_ready(rows):
    return [[float(v) if isinstance(v, decimal.Decimal) else v for v in r] for r in rows]


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


# основной эндпоинт
@app.route('/api/query', methods=['POST'])
def handle_query():
    t0 = time.perf_counter()
    ip = request.remote_addr or "?"
    data = request.get_json(silent=True)
    q = data.get('question') if isinstance(data, dict) else None
    if not isinstance(q, str) or not q.strip():
        return _reject(ip, '', 'Пустой запрос.', 400)
    user_question = q.strip()
    if len(user_question) > MAX_QUESTION_LEN:
        return _reject(ip, user_question[:100], f'Вопрос слишком длинный (максимум {MAX_QUESTION_LEN} символов).', 400)
    if _rate_limited(ip):
        return _reject(ip, user_question, 'Слишком много запросов, подождите минуту.', 429)

    rows, vq, feedback = None, None, None
    error, status = "Не удалось получить ответ.", 200
    key = " ".join(user_question.lower().split())
    cached = _sql_cache.get(key)
    if cached is None and FAST_HOURS.fullmatch(key.strip(" ?!.")):
        cached = validate(FAST_HOURS_SQL, CFG)
    for attempt in (1, 2):
        try:
            if cached and attempt == 1:
                vq = cached
            else:
                sql = generate_sql(user_question, feedback)
                vq = validate_sql(sql, user_question)
            cols, rows = run_select(vq.sql)
            if attempt == 1 and not cached:
                _cache_put(key, vq)
            break
        except LLMError as e:
            error, status = str(e), e.status
            break
        except NoSQL:
            error = "Не удалось построить SQL-запрос к базе университета по этому вопросу. Переформулируйте вопрос."
            break
        except SQLGuardError as e:
            feedback, error = str(e), f"Запрос отклонён проверкой безопасности: {e}"
            if "политика" in str(e):
                break
        except Exception as e:
            print(f"[ERROR] Process query failed: {e}")
            feedback = f"ошибка PostgreSQL: {str(e).splitlines()[0][:150]}"
            error = "Не удалось выполнить запрос к базе данных."
    if rows is None:
        log_event(event="ask", ip=ip, question=user_question, ok=False, sql=vq.sql if vq else None,
                  error=error, ms=int((time.perf_counter() - t0) * 1000))
        return jsonify({'success': False, 'error': error}), status

    cols, rows = mask_pii(cols, rows)
    cols = [AGG_NAMES.get(c.lower(), c) for c in cols]

    warning_msg = ""
    if len(rows) >= vq.limit:
        warning_msg = f"Показаны первые {vq.limit} записей, результат ограничен. Уточните запрос (факультет, кафедра, год)."
    out_rows = _json_ready(rows)
    log_event(event="ask", ip=ip, question=user_question, ok=True, sql=vq.sql, rows=len(rows),
              ms=int((time.perf_counter() - t0) * 1000))
    return jsonify({
        'success': True,
        'sql': vq.sql,
        'answer': _answer(cols, out_rows, len(rows) >= vq.limit, vq.limit),
        'headers': cols,
        'rows': out_rows,
        'warning': warning_msg,
        'explain': vq.explain(),
        'truncated': len(rows) >= vq.limit,
    })


if __name__ == '__main__':
    print("[INFO] Server starting on http://0.0.0.0:5000")

    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)