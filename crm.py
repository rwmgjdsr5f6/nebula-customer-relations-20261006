#!/usr/bin/env python3
"""本地客户关系管理台命令行入口。

仅支持六个行为：
- add:            新增联系人
- list:           列出联系人（可按公司名精确筛选，省略公司时跨全部公司；
                   JSON 或 CSV 输出；可用 --after-id 从指定编号之后继续
                   查询，可用 --limit 限制返回条数）
- get:            按编号查看单条联系人
- update-email:   按编号更新联系人邮箱
- update-company: 按编号更新联系人所属公司
- update-name:    按编号更新联系人姓名
- delete:         按编号删除单条联系人
- company-summary: 按公司汇总联系人数量（JSON 数组，按公司名 Unicode 码点升序）
- add-note:       按编号为联系人追加一条文本备注
- list-notes:     按编号列出联系人的全部备注（按备注编号升序）

数据持久化在通过 --db 指定的 SQLite 数据库文件中，
文件不存在时自动初始化，已存在则复用。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL
)
"""

CREATE_NOTES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL,
    text TEXT NOT NULL
)
"""


MAX_CONTACT_ID = 9223372036854775807
MAX_CONTACT_ID_TEXT = str(MAX_CONTACT_ID)
MAX_CONTACT_ID_DIGITS = len(MAX_CONTACT_ID_TEXT)


def fail(field, message):
    """输出字段错误到标准错误并以退出码 2 结束。"""
    print(f"{field}: {message}", file=sys.stderr)
    sys.exit(2)


def clean(value):
    """清理首尾空白，保留内部字符与大小写。"""
    return value.strip()


def parse_positive_int(raw_value, field):
    """清理首尾空白并校验为正整数（允许前导零），返回整数值。

    只允许 ASCII 数字，数值范围为 1 至 MAX_CONTACT_ID。先剥离前导零再按
    位数与字典序比较上限，仅对不超过上限位数的数字串调用 int()，从而在
    Python 3.11 默认的整数字符串转换位数限制下仍能安全处理超长数字，
    且不额外限制前导零的数量。
    """
    raw_text = clean(raw_value)
    if not raw_text or not all("0" <= ch <= "9" for ch in raw_text):
        fail(field, "must be a positive integer")

    digits = raw_text.lstrip("0")
    if (
        not digits
        or len(digits) > MAX_CONTACT_ID_DIGITS
        or (
            len(digits) == MAX_CONTACT_ID_DIGITS
            and digits > MAX_CONTACT_ID_TEXT
        )
    ):
        fail(field, "must be a positive integer")
    return int(digits)


def parse_contact_id(raw_value):
    """清理编号首尾空白并校验为正整数（允许前导零），返回整数编号。"""
    return parse_positive_int(raw_value, "id")


def valid_email(email):
    """邮箱规则：恰好一个 @、两侧非空、域名至少含一个点且各段非空、无空白。"""
    if any(ch.isspace() for ch in email):
        return False
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    parts = domain.split(".")
    if len(parts) < 2 or any(not part for part in parts):
        return False
    return True


def connect_db(db_path):
    """父目录存在时连接数据库，初始化缺失的表；复用已有数据库。"""
    if not Path(db_path).parent.is_dir():
        fail("db", "parent directory does not exist")
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_NOTES_TABLE_SQL)
    conn.commit()
    return conn


def cmd_add(args):
    name = clean(args.name)
    email = clean(args.email)
    company = clean(args.company)

    if not name:
        fail("name", "must not be empty")
    if not valid_email(email):
        fail("email", "invalid email address")
    if not company:
        fail("company", "must not be empty")

    conn = connect_db(args.db)
    try:
        cursor = conn.execute(
            "INSERT INTO contacts (name, email, company) VALUES (?, ?, ?)",
            (name, email, company),
        )
        conn.commit()
    finally:
        conn.close()

    record = {
        "id": cursor.lastrowid,
        "name": name,
        "email": email,
        "company": company,
    }
    print(json.dumps(record, ensure_ascii=False))
    return 0


def update_contact_field(args, field, raw_value, is_valid, invalid_message, update_sql):
    """按编号更新单个字段的共用流程。

    编号与新值的清理、校验顺序以及数据库访问规则对两个更新入口一致：
    先校验编号，再校验新值，随后连接数据库并核对联系人存在，
    最终只更新目标字段，输出更新后的完整联系人 JSON 对象。
    """
    contact_id = parse_contact_id(args.id)
    new_value = clean(raw_value)
    if not is_valid(new_value):
        fail(field, invalid_message)

    conn = connect_db(args.db)
    try:
        row = conn.execute(
            "SELECT id, name, email, company FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if row is None:
            fail("id", "contact not found")
        conn.execute(update_sql, (new_value, contact_id))
        conn.commit()
    finally:
        conn.close()

    record = {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "company": row[3],
    }
    record[field] = new_value
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_update_email(args):
    return update_contact_field(
        args,
        "email",
        args.email,
        valid_email,
        "invalid email address",
        "UPDATE contacts SET email = ? WHERE id = ?",
    )


def cmd_update_company(args):
    return update_contact_field(
        args,
        "company",
        args.company,
        bool,
        "must not be empty",
        "UPDATE contacts SET company = ? WHERE id = ?",
    )


def cmd_update_name(args):
    return update_contact_field(
        args,
        "name",
        args.name,
        bool,
        "must not be empty",
        "UPDATE contacts SET name = ? WHERE id = ?",
    )


def cmd_get(args):
    contact_id = parse_contact_id(args.id)

    conn = connect_db(args.db)
    try:
        row = conn.execute(
            "SELECT id, name, email, company FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        fail("id", "contact not found")

    record = {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "company": row[3],
    }
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_delete(args):
    contact_id = parse_contact_id(args.id)

    conn = connect_db(args.db)
    try:
        row = conn.execute(
            "SELECT id, name, email, company FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if row is None:
            fail("id", "contact not found")
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
    finally:
        conn.close()

    record = {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "company": row[3],
    }
    print(json.dumps(record, ensure_ascii=False))
    return 0


def csv_field(value):
    """按 CSV 规则转义单个字段：含逗号、双引号、回车或换行时加双引号，
    内部双引号写成两个，其余字段保持原值。"""
    text = str(value)
    if any(ch in text for ch in (",", '"', "\r", "\n")):
        return '"' + text.replace('"', '""') + '"'
    return text


def cmd_list(args):
    output_format = args.format
    if output_format not in ("json", "csv"):
        fail("format", "must be json or csv")

    company = None
    if args.company is not None:
        company = clean(args.company)
        if not company:
            fail("company", "must not be empty")

    name = None
    if args.name is not None:
        name = clean(args.name)
        if not name:
            fail("name", "must not be empty")

    email = None
    if args.email is not None:
        email = clean(args.email)
        if not valid_email(email):
            fail("email", "invalid email address")

    limit = None
    if args.limit is not None:
        limit = parse_positive_int(args.limit, "limit")

    after_id = None
    if args.after_id is not None:
        after_id = parse_positive_int(args.after_id, "after-id")

    conditions = []
    parameters = []
    if after_id is not None:
        conditions.append("id > ?")
        parameters.append(after_id)
    if company is not None:
        conditions.append("company = ?")
        parameters.append(company)
    if name is not None:
        conditions.append("instr(name, ?) > 0")
        parameters.append(name)
    if email is not None:
        conditions.append("email = ?")
        parameters.append(email)

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query_sql = (
        "SELECT id, name, email, company FROM contacts"
        + where_sql
        + " ORDER BY id ASC"
    )
    if limit is not None:
        query_sql += " LIMIT ?"
        parameters.append(limit)

    conn = connect_db(args.db)
    try:
        rows = conn.execute(query_sql, parameters).fetchall()
    finally:
        conn.close()

    records = [
        {"id": row[0], "name": row[1], "email": row[2], "company": row[3]}
        for row in rows
    ]
    if output_format == "csv":
        lines = ["id,name,email,company"]
        for record in records:
            lines.append(
                ",".join(
                    csv_field(record[key]) for key in ("id", "name", "email", "company")
                )
            )
        sys.stdout.write("".join(line + "\r\n" for line in lines))
        return 0
    print(json.dumps(records, ensure_ascii=False))
    return 0


def cmd_company_summary(args):
    """按完整公司名精确归组统计联系人数，输出 JSON 数组。

    每条联系人记录各计一次，按公司名 Unicode 码点顺序升序排列，
    仅含至少一位联系人的公司。SQLite 默认 BINARY 排序按 UTF-8 字节
    比较，其字节序与 Unicode 码点序一致。
    """
    conn = connect_db(args.db)
    try:
        rows = conn.execute(
            "SELECT company, COUNT(*) FROM contacts"
            " GROUP BY company ORDER BY company ASC"
        ).fetchall()
    finally:
        conn.close()

    records = [
        {"company": row[0], "contact_count": row[1]} for row in rows
    ]
    print(json.dumps(records, ensure_ascii=False))
    return 0


def cmd_add_note(args):
    """为联系人追加一条文本备注。

    依次校验编号、正文（清理首尾空白后不得为空）、数据库路径，
    再核对联系人存在，最后写入备注并输出新备注的 JSON 对象。
    """
    contact_id = parse_contact_id(args.id)
    text = clean(args.text)
    if not text:
        fail("text", "must not be empty")

    conn = connect_db(args.db)
    try:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if row is None:
            fail("id", "contact not found")
        cursor = conn.execute(
            "INSERT INTO notes (contact_id, text) VALUES (?, ?)",
            (contact_id, text),
        )
        conn.commit()
    finally:
        conn.close()

    record = {"id": cursor.lastrowid, "contact_id": contact_id, "text": text}
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_list_notes(args):
    """按编号列出联系人的全部备注，按备注编号升序输出 JSON 数组。"""
    contact_id = parse_contact_id(args.id)

    conn = connect_db(args.db)
    try:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if row is None:
            fail("id", "contact not found")
        rows = conn.execute(
            "SELECT id, contact_id, text FROM notes"
            " WHERE contact_id = ? ORDER BY id ASC",
            (contact_id,),
        ).fetchall()
    finally:
        conn.close()

    records = [
        {"id": row[0], "contact_id": row[1], "text": row[2]} for row in rows
    ]
    print(json.dumps(records, ensure_ascii=False))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="crm", description="本地客户关系管理台")
    parser.add_argument("--db", required=True, help="SQLite 数据库文件路径")

    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_add = subparsers.add_parser("add", help="新增联系人")
    parser_add.add_argument("--name", required=True, help="姓名")
    parser_add.add_argument("--email", required=True, help="邮箱")
    parser_add.add_argument("--company", required=True, help="公司名")
    parser_add.set_defaults(func=cmd_add)

    parser_list = subparsers.add_parser("list", help="列出联系人（可按公司筛选）")
    parser_list.add_argument(
        "--company", help="公司名（精确匹配，区分大小写；省略时列出全部公司）"
    )
    parser_list.add_argument("--name", help="姓名子串（字面子串匹配，区分大小写）")
    parser_list.add_argument("--email", help="完整邮箱（精确匹配，区分大小写）")
    parser_list.add_argument(
        "--format", default="json", help="输出格式：json（默认）或 csv"
    )
    parser_list.add_argument(
        "--limit", help="最多返回的条数（正整数；省略时返回全部匹配记录）"
    )
    parser_list.add_argument(
        "--after-id",
        help="仅返回编号严格大于该值的记录（正整数；省略时从首条开始）",
    )
    parser_list.set_defaults(func=cmd_list)

    parser_get = subparsers.add_parser("get", help="按编号查看联系人")
    parser_get.add_argument("--id", required=True, help="联系人编号")
    parser_get.set_defaults(func=cmd_get)

    parser_update = subparsers.add_parser("update-email", help="按编号更新邮箱")
    parser_update.add_argument("--id", required=True, help="联系人编号")
    parser_update.add_argument("--email", required=True, help="新邮箱")
    parser_update.set_defaults(func=cmd_update_email)

    parser_update_company = subparsers.add_parser(
        "update-company", help="按编号更新所属公司"
    )
    parser_update_company.add_argument("--id", required=True, help="联系人编号")
    parser_update_company.add_argument("--company", required=True, help="新公司名")
    parser_update_company.set_defaults(func=cmd_update_company)

    parser_update_name = subparsers.add_parser(
        "update-name", help="按编号更新姓名"
    )
    parser_update_name.add_argument("--id", required=True, help="联系人编号")
    parser_update_name.add_argument("--name", required=True, help="新姓名")
    parser_update_name.set_defaults(func=cmd_update_name)

    parser_delete = subparsers.add_parser("delete", help="按编号删除联系人")
    parser_delete.add_argument("--id", required=True, help="联系人编号")
    parser_delete.set_defaults(func=cmd_delete)

    parser_company_summary = subparsers.add_parser(
        "company-summary", help="按公司汇总联系人数量"
    )
    parser_company_summary.set_defaults(func=cmd_company_summary)

    parser_add_note = subparsers.add_parser("add-note", help="按编号追加文本备注")
    parser_add_note.add_argument("--id", required=True, help="联系人编号")
    parser_add_note.add_argument("--text", required=True, help="备注正文")
    parser_add_note.set_defaults(func=cmd_add_note)

    parser_list_notes = subparsers.add_parser(
        "list-notes", help="按编号列出联系人的全部备注"
    )
    parser_list_notes.add_argument("--id", required=True, help="联系人编号")
    parser_list_notes.set_defaults(func=cmd_list_notes)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
