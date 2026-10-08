"""crm.py delete-note 子命令的回归测试。

覆盖“按备注全局编号删除单条备注”的完整命令行流程：

- 联系人存在且备注属于此人时删除成功：退出码 0、标准错误为空，
  标准输出为被删除备注的单个 JSON 对象，只保留 id/contact_id/text
  原值（正文仅去首尾空白，内部字符原样）；
- 删除后后续独立调用 list-notes 看不到该备注；同文但编号不同的备注、
  其他联系人的备注、联系人资料与数量均不受影响；删除联系人最后一条
  备注后其 list-notes 返回 []；
- --id 与 --note-id 都只接受 ASCII 数字，去首尾空白并允许前导零，
  数值范围为 1 至 9223372036854775807；联系人编号非法报
  id: must be a positive integer，备注编号非法报
  note-id: must be a positive integer，二者同时无效先报前者，
  且输入校验失败不创建数据库文件；
- 编号合法但父目录不存在时报 db: parent directory does not exist；
  联系人不存在时报 id: contact not found；联系人存在但备注不存在、
  已删除或属于他人时均报 note-id: note not found；
- 所有失败均退出码 2、标准输出为空、标准错误仅对应一行；
  已有联系人与备注保持不变；
- 父目录存在而数据库不存在时，沿用有效请求初始化空库的行为，
  再报告联系人不存在。

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

LIN_NAME = "林宁"
LIN_EMAIL = "lin@example.test"
LIN_COMPANY = "星河科技"

ZHOU_NAME = "周岚"
ZHOU_EMAIL = "zhou@example.test"
ZHOU_COMPANY = "远帆咨询"

ID_ERROR_LINE = "id: must be a positive integer"
NOTE_ID_ERROR_LINE = "note-id: must be a positive integer"
CONTACT_NOT_FOUND_LINE = "id: contact not found"
NOTE_NOT_FOUND_LINE = "note-id: note not found"
DB_ERROR_LINE = "db: parent directory does not exist"

# 两个编号共用的非法写法：0、非数字、负数、小数、纯空白、超过 64 位
# 有符号整数上限，以及远超上限的超长数字串
INVALID_IDS = [
    "0",
    "abc",
    "12x",
    "-1",
    "1.5",
    "   ",
    "9223372036854775808",
    "9" * 5000,
]

MAX_ID = "9223372036854775807"


class DeleteNoteFlowTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, db_path, name, email, company):
        return self.run_crm(
            db_path, "add", "--name", name, "--email", email, "--company", company
        )

    def add_note(self, db_path, contact_id, text):
        return self.run_crm(
            db_path, "add-note", "--id", str(contact_id), "--text", text
        )

    def delete_note(self, db_path, contact_id, note_id):
        return self.run_crm(
            db_path,
            "delete-note",
            "--id",
            str(contact_id),
            "--note-id",
            str(note_id),
        )

    def list_notes(self, db_path, contact_id):
        return self.run_crm(db_path, "list-notes", "--id", str(contact_id))

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    # ---- 断言辅助 ----

    def assert_add_contact_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(record, expected)
        return record

    def assert_add_note_success(self, result, contact_id, expected_text):
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        self.assertEqual(record["contact_id"], contact_id)
        self.assertEqual(record["text"], expected_text)
        return record

    def assert_delete_note_success(self, result, expected_record):
        """断言 delete-note 成功：退出 0、stderr 空，stdout 为被删备注对象。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        self.assertEqual(record, expected_record)
        return record

    def assert_list_notes_success(self, db_path, contact_id, expected_records):
        result = self.list_notes(db_path, contact_id)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def assert_rejected(self, result, expected_stderr_line):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    # ---- 固定合成数据 ----

    def seed_two_contacts(self):
        """新增林宁（1，星河科技）与周岚（2，远帆咨询）。"""
        lin = self.assert_add_contact_success(
            self.add_contact(self.db_path, LIN_NAME, LIN_EMAIL, LIN_COMPANY),
            {"id": 1, "name": LIN_NAME, "email": LIN_EMAIL, "company": LIN_COMPANY},
        )
        zhou = self.assert_add_contact_success(
            self.add_contact(self.db_path, ZHOU_NAME, ZHOU_EMAIL, ZHOU_COMPANY),
            {"id": 2, "name": ZHOU_NAME, "email": ZHOU_EMAIL, "company": ZHOU_COMPANY},
        )
        return lin, zhou

    def seed_three_notes(self):
        """追加林宁首次联系(1)、周岚已发资料(2)、林宁下周联系(3)。"""
        note1 = self.assert_add_note_success(
            self.add_note(self.db_path, 1, "首次联系"), 1, "首次联系"
        )
        note2 = self.assert_add_note_success(
            self.add_note(self.db_path, 2, "已发资料"), 2, "已发资料"
        )
        note3 = self.assert_add_note_success(
            self.add_note(self.db_path, 1, "下周联系"), 1, "下周联系"
        )
        self.assertEqual([note1["id"], note2["id"], note3["id"]], [1, 2, 3])
        return note1, note2, note3

    def assert_contacts_unchanged(self, lin, zhou):
        """两名联系人的资料与数量均保持不变。"""
        self.assert_company_list_succeeds(LIN_COMPANY, [lin])
        self.assert_company_list_succeeds(ZHOU_COMPANY, [zhou])
        for expected in (lin, zhou):
            result = self.get_contact(self.db_path, expected["id"])
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout.decode("utf-8")), expected)

    def assert_company_list_succeeds(self, company, expected_records):
        result = self.list_company(self.db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), expected_records)

    # ---- 删除主流程 ----

    def test_delete_returns_original_note_and_list_no_longer_contains_it(self):
        lin, zhou = self.seed_two_contacts()
        note1, note2, note3 = self.seed_three_notes()

        # 删除林宁的备注 1：输出被删备注原值
        result = self.delete_note(self.db_path, 1, 1)
        self.assert_delete_note_success(result, note1)

        # 后续独立调用：林宁只剩编号 3，周岚仍有编号 2
        self.assert_list_notes_success(self.db_path, 1, [note3])
        self.assert_list_notes_success(self.db_path, 2, [note2])

        # 联系人资料与数量不变
        self.assert_contacts_unchanged(lin, zhou)

    def test_delete_last_note_leaves_empty_array(self):
        self.seed_two_contacts()
        note1, _note2, note3 = self.seed_three_notes()

        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, 1), note1
        )
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, 3), note3
        )
        # 删除最后一条备注后该联系人返回 []
        result = self.list_notes(self.db_path, 1)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.decode("utf-8"), "[]\n")

    def test_delete_does_not_affect_duplicate_text_or_other_notes(self):
        self.seed_two_contacts()
        first = self.assert_add_note_success(
            self.add_note(self.db_path, 1, "同文备注"), 1, "同文备注"
        )
        other_contact_note = self.assert_add_note_success(
            self.add_note(self.db_path, 2, "同文备注"), 2, "同文备注"
        )
        duplicate = self.assert_add_note_success(
            self.add_note(self.db_path, 1, "同文备注"), 1, "同文备注"
        )

        # 删除编号最小的同文备注，另一条同文但编号不同的备注保留
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, first["id"]), first
        )
        self.assert_list_notes_success(self.db_path, 1, [duplicate])
        # 他人的备注（正文恰好相同）不受影响
        self.assert_list_notes_success(self.db_path, 2, [other_contact_note])

    def test_delete_preserves_text_with_inner_whitespace(self):
        self.seed_two_contacts()
        raw_text = "  \t首行  内有空格\n次行\t制表  \n "
        note = self.assert_add_note_success(
            self.add_note(self.db_path, 1, raw_text), 1, raw_text.strip()
        )
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, note["id"]), note
        )
        self.assert_list_notes_success(self.db_path, 1, [])

    def test_padded_and_spaced_ids_still_target_owner(self):
        self.seed_two_contacts()
        note = self.assert_add_note_success(
            self.add_note(self.db_path, 2, "周岚备注"), 2, "周岚备注"
        )
        # 联系人编号与备注编号带首尾空白、前导零仍命中同一归属
        result = self.run_crm(
            self.db_path,
            "delete-note",
            "--id",
            "  002  ",
            "--note-id",
            "\t000" + str(note["id"]) + " ",
        )
        self.assert_delete_note_success(result, note)
        self.assert_list_notes_success(self.db_path, 2, [])

    def test_note_ids_continue_autoincrement_after_delete(self):
        self.seed_two_contacts()
        note1, _note2, note3 = self.seed_three_notes()
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, 1), note1
        )
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, 3), note3
        )
        # 删除后追加的备注接续全局自增序列，编号为 4，不被复用
        new_note = self.assert_add_note_success(
            self.add_note(self.db_path, 1, "删除后的新备注"), 1, "删除后的新备注"
        )
        self.assertEqual(new_note["id"], 4)
        self.assert_list_notes_success(self.db_path, 1, [new_note])

    # ---- 编号校验 ----

    def test_invalid_contact_id_reports_id_error(self):
        self.seed_two_contacts()
        self.seed_three_notes()
        snapshot = self.snapshot_all_notes()

        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id[:8]):
                result = self.run_crm(
                    self.db_path,
                    "delete-note",
                    "--id",
                    raw_id,
                    "--note-id",
                    "1",
                )
                self.assert_rejected(result, ID_ERROR_LINE)
        self.assert_notes_unchanged(snapshot)

    def test_invalid_note_id_reports_note_id_error(self):
        self.seed_two_contacts()
        self.seed_three_notes()
        snapshot = self.snapshot_all_notes()

        for raw_note_id in INVALID_IDS:
            with self.subTest(raw_note_id=raw_note_id[:8]):
                result = self.run_crm(
                    self.db_path,
                    "delete-note",
                    "--id",
                    "1",
                    "--note-id",
                    raw_note_id,
                )
                self.assert_rejected(result, NOTE_ID_ERROR_LINE)
        self.assert_notes_unchanged(snapshot)

    def test_both_ids_invalid_reports_contact_id_first(self):
        for raw_id, raw_note_id in (
            ("0", "0"),
            ("abc", "-1"),
            ("-1", "abc"),
            ("9" * 5000, "1.5"),
            ("1.5", "9" * 5000),
        ):
            with self.subTest(raw_id=raw_id[:8], raw_note_id=raw_note_id[:8]):
                result = self.run_crm(
                    self.db_path,
                    "delete-note",
                    "--id",
                    raw_id,
                    "--note-id",
                    raw_note_id,
                )
                self.assert_rejected(result, ID_ERROR_LINE)

    def test_max_boundary_ids_parse_then_report_not_found(self):
        # 上限值本身是合法编号；库中无此联系人/备注，进入数据库阶段后
        # 先报联系人不存在
        self.seed_two_contacts()
        result = self.run_crm(
            self.db_path,
            "delete-note",
            "--id",
            MAX_ID,
            "--note-id",
            MAX_ID,
        )
        self.assert_rejected(result, CONTACT_NOT_FOUND_LINE)

    # ---- 不存在 / 归属错误 ----

    def test_unknown_contact_reports_contact_not_found(self):
        self.seed_two_contacts()
        snapshot = self.snapshot_all_notes()

        result = self.delete_note(self.db_path, 99, 1)
        self.assert_rejected(result, CONTACT_NOT_FOUND_LINE)
        self.assert_notes_unchanged(snapshot)

    def test_note_not_found_when_missing_deleted_or_owned_by_other(self):
        self.seed_two_contacts()
        note1, note2, note3 = self.seed_three_notes()

        # 联系人存在但备注编号不存在
        result = self.delete_note(self.db_path, 1, 99)
        self.assert_rejected(result, NOTE_NOT_FOUND_LINE)

        # 备注属于其他联系人（备注 2 属于周岚，林宁删除它报 note not found）
        result = self.delete_note(self.db_path, 1, note2["id"])
        self.assert_rejected(result, NOTE_NOT_FOUND_LINE)

        # 已删除的备注再次删除
        self.assert_delete_note_success(
            self.delete_note(self.db_path, 1, note1["id"]), note1
        )
        result = self.delete_note(self.db_path, 1, note1["id"])
        self.assert_rejected(result, NOTE_NOT_FOUND_LINE)

        # 全部失败后未被涉及的备注保持原样
        self.assert_list_notes_success(self.db_path, 1, [note3])
        self.assert_list_notes_success(self.db_path, 2, [note2])

    # ---- 数据库路径与建库边界 ----

    def test_missing_parent_directory_reports_db_error(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"
        result = self.run_crm(
            fresh_db, "delete-note", "--id", "1", "--note-id", "1"
        )
        self.assert_rejected(result, DB_ERROR_LINE)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_invalid_inputs_do_not_create_missing_database(self):
        index = 0
        cases = [
            ("bad", "1", ID_ERROR_LINE),
            ("1", "bad", NOTE_ID_ERROR_LINE),
            ("bad", "bad", ID_ERROR_LINE),
            ("0", "0", ID_ERROR_LINE),
        ]
        for raw_id, raw_note_id, expected_error in cases:
            fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
            index += 1
            with self.subTest(raw_id=raw_id, raw_note_id=raw_note_id):
                self.assertFalse(fresh_db.exists())
                result = self.run_crm(
                    fresh_db,
                    "delete-note",
                    "--id",
                    raw_id,
                    "--note-id",
                    raw_note_id,
                )
                self.assert_rejected(result, expected_error)
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_valid_params_with_unknown_contact_leave_initialized_empty_database(
        self,
    ):
        fresh_db = self.tmpdir / "delete-note-empty.sqlite3"
        self.assertFalse(fresh_db.exists())
        result = self.run_crm(
            fresh_db, "delete-note", "--id", "99", "--note-id", "1"
        )
        self.assert_rejected(result, CONTACT_NOT_FOUND_LINE)
        self.assertTrue(fresh_db.exists())

        with sqlite3.connect(fresh_db) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type='table' AND name IN ('contacts', 'notes')"
                ).fetchall(),
                [("contacts",), ("notes",)],
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )

    def test_failures_leave_contacts_and_notes_unchanged(self):
        lin, zhou = self.seed_two_contacts()
        self.seed_three_notes()
        snapshot = self.snapshot_all_notes()

        # 各类失败后数据均不变
        self.assert_rejected(
            self.run_crm(
                self.tmpdir / "missing-parent" / "x.sqlite3",
                "delete-note",
                "--id",
                "1",
                "--note-id",
                "1",
            ),
            DB_ERROR_LINE,
        )
        self.assert_rejected(
            self.delete_note(self.db_path, 99, 1), CONTACT_NOT_FOUND_LINE
        )
        self.assert_rejected(
            self.delete_note(self.db_path, 1, 2), NOTE_NOT_FOUND_LINE
        )
        self.assert_rejected(
            self.run_crm(
                self.db_path,
                "delete-note",
                "--id",
                "0",
                "--note-id",
                "1",
            ),
            ID_ERROR_LINE,
        )
        self.assert_rejected(
            self.run_crm(
                self.db_path,
                "delete-note",
                "--id",
                "1",
                "--note-id",
                "0",
            ),
            NOTE_ID_ERROR_LINE,
        )

        self.assert_notes_unchanged(snapshot)
        self.assert_contacts_unchanged(lin, zhou)

    # ---- 快照辅助 ----

    def snapshot_all_notes(self):
        records = {}
        for contact_id in (1, 2):
            result = self.list_notes(self.db_path, contact_id)
            records[contact_id] = json.loads(result.stdout.decode("utf-8"))
        return records

    def assert_notes_unchanged(self, snapshot):
        for contact_id, expected in snapshot.items():
            self.assert_list_notes_success(self.db_path, contact_id, expected)


if __name__ == "__main__":
    unittest.main()
