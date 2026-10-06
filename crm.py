#!/usr/bin/env python3
"""本地客户关系管理台命令行入口。

仅支持四个行为：
- add:            新增联系人
- list:           按公司名精确筛选联系人
- update-email:   按编号更新联系人邮箱
- update-company: 按编号更新联系人所属公司

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


def fail(field, message):
    """输出字段错误到标准错误并以退出码 2 结束。"""
    print(f"{field}: {message}", file=sys.stderr)
    sys.exit(2)


def clean(value):
    """清理首尾空白，保留内部字符与大小写。"""
    return value.strip()


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


def parse_contact_id(raw):
    """清理并校验编号：纯 ASCII 数字且在 64 位有符号正整数范围内。"""
    raw_id = clean(raw)
    if (
        not raw_id
        or not all("0" <= ch <= "9" for ch in raw_id)
        or not 1 <= int(raw_id) <= 9223372036854775807
    ):
        fail("id", "must be a positive integer")
    return int(raw_id)


def update_contact(db_path, contact_id, field, value):
    """更新指定编号联系人的单个字段，返回更新后的完整记录。"""
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, email, company FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        if row is None:
            fail("id", "contact not found")
        conn.execute(
            f"UPDATE contacts SET {field} = ? WHERE id = ?",
            (value, contact_id),
        )
        conn.commit()
    finally:
        conn.close()

    record = {"id": row[0], "name": row[1], "email": row[2], "company": row[3]}
    record[field] = value
    return record


def cmd_update_email(args):
    contact_id = parse_contact_id(args.id)
    email = clean(args.email)

    if not valid_email(email):
        fail("email", "invalid email address")

    record = update_contact(args.db, contact_id, "email", email)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_update_company(args):
    contact_id = parse_contact_id(args.id)
    company = clean(args.company)

    if not company:
        fail("company", "must not be empty")

    record = update_contact(args.db, contact_id, "company", company)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_list(args):
    company = clean(args.company)
    if not company:
        fail("company", "must not be empty")

    name = None
    if args.name is not None:
        name = clean(args.name)
        if not name:
            fail("name", "must not be empty")

    conn = connect_db(args.db)
    try:
        if name is None:
            rows = conn.execute(
                "SELECT id, name, email, company "
                "FROM contacts WHERE company = ? ORDER BY id ASC",
                (company,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, email, company "
                "FROM contacts WHERE company = ? AND instr(name, ?) > 0 "
                "ORDER BY id ASC",
                (company, name),
            ).fetchall()
    finally:
        conn.close()

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
    parser_list.set_defaults(func=cmd_list)

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

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
