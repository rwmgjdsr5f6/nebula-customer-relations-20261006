"""既有 SQLite 数据库（仅有 contacts 表）首次使用备注功能的回归测试。

样例数据库模拟 crm.py 支持备注之前留下的既有库：只含当前格式的
contacts 表（带 AUTOINCREMENT 自增编号信息），不含 notes 表，且在首次
备注操作之前未经任何其他产品命令访问。预置三位联系人：

- 编号 7  林宁（星河科技，lin@example.test）
- 编号 11 许禾（星河科技，xu@example.test）
- 编号 15 周岚（远帆咨询，zhou@example.test）

覆盖两条首次初始化路径与初始化边界下的错误结果：

- 查询先发生：list-notes --id 7 输出 [] 并补建 notes 表，随后
  add-note --id 7 --text " 首次联系 " 输出编号 1、contact_id 7、
  正文 "首次联系" 的单个 JSON 对象；
- 追加先发生：相同初始状态的样例直接 add-note，返回完全相同的结果；
- 两条路径之后都通过新的独立命令调用重新查询：编号 7 的 list-notes
  仅返回这条备注，编号 11 与 15 仍返回 []，重复查询不会清空备注；
- 在未补表的样例上，list-notes --id 0 报 id: must be a positive integer、
  add-note --id 7 --text "   " 报 text: must not be empty，二者退出码 2、
  标准输出为空，且 notes 表仍不存在；
- 在未补表的样例上，list-notes --id 99 先初始化 notes 表，再以退出码 2、
  空标准输出与标准错误 id: contact not found 结束；
- 所有用例均核对三位联系人的编号、完整字段与数量保持不变。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests
"""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

# 与 crm.py 当前版本一致的 contacts 表结构（含 AUTOINCREMENT 自增编号信息）
LEGACY_CREATE_CONTACTS_SQL = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL
)
"""

LIN = {"id": 7, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}
XU = {"id": 11, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}
ZHOU = {"id": 15, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}
SEED_CONTACTS = [LIN, XU, ZHOU]

NOTE_RAW_TEXT = " 首次联系 "
NOTE_TEXT = "首次联系"
EXPECTED_NOTE = {"id": 1, "contact_id": LIN["id"], "text": NOTE_TEXT}

ID_ERROR_LINE = "id: must be a positive integer"
TEXT_ERROR_LINE = "text: must not be empty"
NOT_FOUND_LINE = "id: contact not found"


class LegacyDatabaseNotesInitTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)

    # ---- 样例数据库与命令执行 ----

    def make_legacy_db(self, name="legacy.sqlite3"):
        """构建仅有 contacts 表的既有库：三位联系人、自增编号信息、无 notes 表。"""
        db_path = self.tmpdir / name
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(LEGACY_CREATE_CONTACTS_SQL)
            for contact in SEED_CONTACTS:
                conn.execute(
                    "INSERT INTO contacts (id, name, email, company)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        contact["id"],
                        contact["name"],
                        contact["email"],
                        contact["company"],
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        # 初始状态自检：无 notes 表，自增编号信息已推进到 15
        self.assertFalse(self.notes_table_exists(db_path))
        with sqlite3.connect(db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name = 'contacts'"
                ).fetchone(),
                (ZHOU["id"],),
            )
        self.assert_contacts_intact(db_path)
        return db_path

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_note(self, db_path, contact_id, text):
        return self.run_crm(
            db_path, "add-note", "--id", str(contact_id), "--text", text
        )

    def list_notes(self, db_path, contact_id):
        return self.run_crm(db_path, "list-notes", "--id", str(contact_id))

    # ---- 断言辅助 ----

    def notes_table_exists(self, db_path):
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name = 'notes'"
            ).fetchone()
        return row is not None

    def assert_contacts_intact(self, db_path):
        """三位联系人的编号、完整字段与数量均保持初始状态。"""
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, email, company FROM contacts ORDER BY id ASC"
            ).fetchall()
        records = [
            {"id": row[0], "name": row[1], "email": row[2], "company": row[3]}
            for row in rows
        ]
        self.assertEqual(records, SEED_CONTACTS)
        self.assertEqual(len(records), 3)

    def assert_command_success(self, result):
        """断言命令成功：退出码 0、标准错误为空。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

    def assert_rejected(self, result, expected_stderr_line):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    def assert_add_note_success(self, result):
        """断言 add-note 输出恰为期望的单个备注 JSON 对象。"""
        self.assert_command_success(result)
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        self.assertEqual(record, EXPECTED_NOTE)
        return record

    def assert_list_notes_output(self, db_path, contact_id, expected_records):
        """通过新的独立命令调用查询备注，结果与期望完全一致。"""
        result = self.list_notes(db_path, contact_id)
        self.assert_command_success(result)
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def assert_final_note_state(self, db_path):
        """两条初始化路径共用的最终状态核对。

        编号 7 仅有这条备注，编号 11 与 15 仍为空，重复查询不会清空备注，
        三位联系人的资料与数量保持不变。
        """
        self.assert_list_notes_output(db_path, LIN["id"], [EXPECTED_NOTE])
        self.assert_list_notes_output(db_path, XU["id"], [])
        self.assert_list_notes_output(db_path, ZHOU["id"], [])

        # 重复查询不会清空备注
        self.assert_list_notes_output(db_path, LIN["id"], [EXPECTED_NOTE])
        self.assert_list_notes_output(db_path, LIN["id"], [EXPECTED_NOTE])

        self.assert_contacts_intact(db_path)

    # ---- 查询先发生的初始化路径 ----

    def test_list_notes_first_initializes_notes_table(self):
        db_path = self.make_legacy_db()

        # 首次备注操作即查询：输出空数组并补建 notes 表
        result = self.list_notes(db_path, LIN["id"])
        self.assert_command_success(result)
        self.assertEqual(result.stdout.decode("utf-8"), "[]\n")
        self.assertTrue(self.notes_table_exists(db_path))
        self.assert_contacts_intact(db_path)

        # 随后追加：编号 1、contact_id 7、正文去除首尾空白
        self.assert_add_note_success(self.add_note(db_path, LIN["id"], NOTE_RAW_TEXT))

        self.assert_final_note_state(db_path)

    # ---- 追加先发生的初始化路径 ----

    def test_add_note_first_initializes_notes_table(self):
        db_path = self.make_legacy_db()

        # 首次备注操作即追加：结果与查询先发生的路径完全相同
        self.assert_add_note_success(self.add_note(db_path, LIN["id"], NOTE_RAW_TEXT))
        self.assertTrue(self.notes_table_exists(db_path))

        self.assert_final_note_state(db_path)

    # ---- 初始化边界下的错误结果 ----

    def test_list_notes_invalid_id_leaves_notes_table_absent(self):
        db_path = self.make_legacy_db()

        result = self.list_notes(db_path, 0)
        self.assert_rejected(result, ID_ERROR_LINE)

        # 输入校验失败发生在初始化之前：notes 表仍不存在
        self.assertFalse(self.notes_table_exists(db_path))
        self.assert_contacts_intact(db_path)

    def test_add_note_blank_text_leaves_notes_table_absent(self):
        db_path = self.make_legacy_db()

        result = self.add_note(db_path, LIN["id"], "   ")
        self.assert_rejected(result, TEXT_ERROR_LINE)

        # 输入校验失败发生在初始化之前：notes 表仍不存在
        self.assertFalse(self.notes_table_exists(db_path))
        self.assert_contacts_intact(db_path)

    def test_list_notes_unknown_id_initializes_table_then_reports_not_found(self):
        db_path = self.make_legacy_db()

        result = self.list_notes(db_path, 99)
        self.assert_rejected(result, NOT_FOUND_LINE)

        # 合法编号先触发 notes 表初始化，再报告联系人不存在
        self.assertTrue(self.notes_table_exists(db_path))
        with sqlite3.connect(db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )
        self.assert_contacts_intact(db_path)


if __name__ == "__main__":
    unittest.main()
