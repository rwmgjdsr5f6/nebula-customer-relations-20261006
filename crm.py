#!/usr/bin/env python3
"""本地客户关系管理台命令行入口。

仅支持六个行为：
- add:            新增联系人
- list:           按公司名精确筛选联系人
- get:            按编号查看单条联系人
- update-email:   按编号更新联系人邮箱
- update-company: 按编号更新联系人所属公司
- update-name:    按编号更新联系人姓名
- delete:         按编号删除单条联系人

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


def parse_contact_id(raw_value):
    """清理编号首尾空白并校验为正整数（允许前导零），返回整数编号。

    只允许 ASCII 数字，数值范围为 1 至 MAX_CONTACT_ID。先剥离前导零再按
    位数与字典序比较上限，仅对不超过上限位数的数字串调用 int()，从而在
    Python 3.11 默认的整数字符串转换位数限制下仍能安全处理超长编号，
    且不额外限制前导零的数量。
    """
    raw_id = clean(raw_value)
    if not raw_id or not all("0" <= ch <= "9" for ch in raw_id):
        fail("id", "must be a positive integer")

    digits = raw_id.lstrip("0")
    if (
        not digits
        or len(digits) > MAX_CONTACT_ID_DIGITS
        or (
            len(digits) == MAX_CONTACT_ID_DIGITS
            and digits > MAX_CONTACT_ID_TEXT
        )
    ):
        fail("id", "must be a positive integer")
    return int(digits)


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
    """按 RFC 4180 最小转义规则编码单个 CSV 字段。

    仅当字段包含逗号、双引号、回车或换行时才用双引号包裹，
    内部双引号写成两个；其余字段保持原值、不加引号。
    """
    if any(ch in value for ch in (",", '"', "\r", "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


def render_csv(rows):
    """将联系人行渲染为 CSV：固定表头，记录按给定顺序排列，行尾均为 CRLF。"""
    lines = ["id,name,email,company"]
    for contact_id, name, email, company in rows:
        lines.append(
            ",".join(
                [
                    str(contact_id),
                    csv_field(name),
                    csv_field(email),
                    csv_field(company),
                ]
            )
        )
    return "\r\n".join(lines) + "\r\n"


def cmd_list(args):
    output_format = args.format
    if output_format not in ("json", "csv"):
        fail("format", "must be json or csv")

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

    conditions = ["company = ?"]
    parameters = [company]
    if name is not None:
        conditions.append("instr(name, ?) > 0")
        parameters.append(name)
    if email is not None:
        conditions.append("email = ?")
        parameters.append(email)

    query_sql = (
        "SELECT id, name, email, company FROM contacts WHERE "
        + " AND ".join(conditions)
        + " ORDER BY id ASC"
    )

    conn = connect_db(args.db)
    try:
        rows = conn.execute(query_sql, parameters).fetchall()
    finally:
        conn.close()

    if output_format == "csv":
        # UTF-8 无 BOM；无匹配时只输出表头
        sys.stdout.write(render_csv(rows))
        return 0

    records = [
        {"id": row[0], "name": row[1], "email": row[2], "company": row[3]}
        for row in rows
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

    parser_list = subparsers.add_parser("list", help="按公司筛选联系人")
    parser_list.add_argument("--company", required=True, help="公司名")
    parser_list.add_argument("--name", help="姓名子串（字面子串匹配，区分大小写）")
    parser_list.add_argument("--email", help="完整邮箱（精确匹配，区分大小写）")
    parser_list.add_argument(
        "--format",
        default="json",
        help="输出格式：json（默认）或 csv",
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

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
