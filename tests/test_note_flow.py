"""crm.py add-note / list-notes 子命令的回归测试。

覆盖“为联系人追加备注后重新查询”的完整命令行流程：

- 联系人尚无备注时 list-notes 成功返回空数组；
- 在两名联系人之间交替追加备注，add-note 成功时退出码 0、标准错误为空，
  输出只含 id/contact_id/text 的 JSON 对象，编号为正整数、归属编号正确、
  正文仅去除首尾空白（保留中文、内部空格与换行）；
- 通过新的命令调用重新查询同一数据库，结果按备注编号升序、与追加输出
  逐字段一致，且不会混入另一联系人的备注；
- 重复追加相同正文产生两条编号不同的独立记录；
- 编号带首尾空白与前导零时两个入口仍指向同一联系人，备注操作不改变
  联系人资料与数量；
- 编号为 0、非数字或超过 9223372036854775807 时两个入口均以退出码 2
  结束，标准输出为空，标准错误恰为一行 id: must be a positive integer；
- add-note 正文为空或纯空白时报 text: must not be empty，编号与正文
  同时无效时先报编号错误；
- 合法编号 99 不存在时两个入口均报 id: contact not found；参数合法但
  数据库父目录不存在时均报 db: parent directory does not exist；
- 失败后已有联系人与备注保持不变；输入校验失败不创建数据库文件，
  合法参数在父目录存在的新数据库上遇到联系人不存在时保留已初始化的空库。

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
TEXT_ERROR_LINE = "text: must not be empty"
NOT_FOUND_LINE = "id: contact not found"
DB_ERROR_LINE = "db: parent directory does not exist"

# 两个入口共用的无效编号：0、非数字、负数、小数、纯空白、超出 64 位
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

# add-note 的空或纯空白正文
BLANK_TEXTS = ["", "   ", "\t\t", " \n\t "]

# 林宁的两条备注原始输入：首尾带空白，正文含中文、内部空格与换行
LIN_NOTE_RAW_1 = "  \t林宁备注甲：含中文 与  内部空格\n还有换行\t段落  \n "
LIN_NOTE_RAW_2 = "\t 林宁备注乙：第二条\n再 一 行 \t"

# 周岚的两条备注原始输入（其中一条也带首尾空白）
ZHOU_NOTE_RAW_1 = "周岚备注 ONE"
ZHOU_NOTE_RAW_2 = "  周岚备注 TWO：远帆咨询第二条  "


class NoteFlowTestCase(unittest.TestCase):
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

    def list_notes(self, db_path, contact_id):
        return self.run_crm(db_path, "list-notes", "--id", str(contact_id))

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    # ---- 断言辅助 ----

    def assert_add_contact_success(self, result, expected):
        """断言 add 成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record, expected)
        return record

    def assert_add_note_success(self, result, contact_id, expected_text):
        """断言 add-note 成功并返回解析后的备注字典。

        退出码 0、标准错误为空；标准输出整体是单个 JSON 对象，只含
        id/contact_id/text 三个字段，编号为正整数、归属编号与正文正确。
        """
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        self.assertIsInstance(record["id"], int)
        self.assertGreater(record["id"], 0)
        self.assertEqual(record["contact_id"], contact_id)
        self.assertEqual(record["text"], expected_text)
        return record

    def assert_list_notes_success(self, db_path, contact_id, expected_records):
        """断言 list-notes 返回的备注（含顺序）与期望完全一致。"""
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

    def assert_company_list(self, db_path, company, expected_records):
        """断言按公司查询到的联系人与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    # ---- 固定合成数据 ----

    def seed_two_contacts(self):
        """在全新数据库依次新增林宁（星河科技）与周岚（远帆咨询）。"""
        lin = self.assert_add_contact_success(
            self.add_contact(self.db_path, LIN_NAME, LIN_EMAIL, LIN_COMPANY),
            {"id": 1, "name": LIN_NAME, "email": LIN_EMAIL, "company": LIN_COMPANY},
        )
        zhou = self.assert_add_contact_success(
            self.add_contact(self.db_path, ZHOU_NAME, ZHOU_EMAIL, ZHOU_COMPANY),
            {"id": 2, "name": ZHOU_NAME, "email": ZHOU_EMAIL, "company": ZHOU_COMPANY},
        )
        self.assertLess(lin["id"], zhou["id"])
        return lin, zhou

    def assert_contacts_unchanged(self, lin, zhou):
        """两名联系人的资料与数量均保持不变。"""
        self.assert_company_list(self.db_path, LIN_COMPANY, [lin])
        self.assert_company_list(self.db_path, ZHOU_COMPANY, [zhou])

        result_lin = self.get_contact(self.db_path, lin["id"])
        self.assertEqual(result_lin.returncode, 0, result_lin.stderr.decode("utf-8"))
        self.assertEqual(result_lin.stderr, b"")
        self.assertEqual(json.loads(result_lin.stdout.decode("utf-8")), lin)

        result_zhou = self.get_contact(self.db_path, zhou["id"])
        self.assertEqual(result_zhou.returncode, 0, result_zhou.stderr.decode("utf-8"))
        self.assertEqual(result_zhou.stderr, b"")
        self.assertEqual(json.loads(result_zhou.stdout.decode("utf-8")), zhou)

    def notes_snapshot(self):
        """记录两名联系人当前的全部备注（含顺序）。"""
        lin_records = json.loads(
            self.list_notes(self.db_path, 1).stdout.decode("utf-8")
        )
        zhou_records = json.loads(
            self.list_notes(self.db_path, 2).stdout.decode("utf-8")
        )
        return lin_records, zhou_records

    def assert_notes_unchanged(self, snapshot):
        lin_records, zhou_records = snapshot
        self.assert_list_notes_success(self.db_path, 1, lin_records)
        self.assert_list_notes_success(self.db_path, 2, zhou_records)

    # ---- 追加后重新查询的主流程 ----

    def test_list_notes_returns_empty_array_when_contact_has_no_notes(self):
        lin, zhou = self.seed_two_contacts()

        for contact in (lin, zhou):
            with self.subTest(contact=contact["name"]):
                result = self.list_notes(self.db_path, contact["id"])
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")
                # 标准输出整体就是空 JSON 数组，无多余输出
                self.assertEqual(result.stdout.decode("utf-8"), "[]\n")

    def test_alternating_add_notes_then_relist_matches_outputs(self):
        lin, zhou = self.seed_two_contacts()

        # 初始两人均无备注
        self.assert_list_notes_success(self.db_path, lin["id"], [])
        self.assert_list_notes_success(self.db_path, zhou["id"], [])

        # 交替为两人追加备注
        note_lin_1 = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], LIN_NOTE_RAW_1),
            lin["id"],
            LIN_NOTE_RAW_1.strip(),
        )
        note_zhou_1 = self.assert_add_note_success(
            self.add_note(self.db_path, zhou["id"], ZHOU_NOTE_RAW_1),
            zhou["id"],
            ZHOU_NOTE_RAW_1.strip(),
        )
        note_lin_2 = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], LIN_NOTE_RAW_2),
            lin["id"],
            LIN_NOTE_RAW_2.strip(),
        )
        note_zhou_2 = self.assert_add_note_success(
            self.add_note(self.db_path, zhou["id"], ZHOU_NOTE_RAW_2),
            zhou["id"],
            ZHOU_NOTE_RAW_2.strip(),
        )

        # 备注编号按追加顺序严格递增
        self.assertLess(note_lin_1["id"], note_zhou_1["id"])
        self.assertLess(note_zhou_1["id"], note_lin_2["id"])
        self.assertLess(note_lin_2["id"], note_zhou_2["id"])

        # 林宁的正文保留中文、内部双空格、内部制表符与换行，仅去掉首尾空白
        lin_text = note_lin_1["text"]
        self.assertIn("林宁备注甲", lin_text)
        self.assertIn("  ", lin_text)
        self.assertIn("\t", lin_text)
        self.assertIn("\n", lin_text)
        self.assertEqual(lin_text, LIN_NOTE_RAW_1.strip())
        self.assertTrue(lin_text[0] not in " \t\r\n")
        self.assertTrue(lin_text[-1] not in " \t\r\n")
        self.assertIn("再 一 行", note_lin_2["text"])
        self.assertEqual(note_zhou_2["text"], ZHOU_NOTE_RAW_2.strip())

        # 重复追加相同正文产生两条编号不同的独立记录
        note_lin_dup = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], LIN_NOTE_RAW_1),
            lin["id"],
            LIN_NOTE_RAW_1.strip(),
        )
        self.assertNotEqual(note_lin_dup["id"], note_lin_1["id"])
        self.assertEqual(note_lin_dup["text"], note_lin_1["text"])
        self.assertEqual(note_lin_dup["contact_id"], lin["id"])

        # 通过新的命令调用查询同一数据库：林宁的备注按编号升序，
        # 与追加输出逐条一致，且不混入周岚的备注
        lin_records = self.assert_list_notes_success(
            self.db_path,
            lin["id"],
            [note_lin_1, note_lin_2, note_lin_dup],
        )
        self.assertEqual(
            [record["id"] for record in lin_records],
            sorted(record["id"] for record in lin_records),
        )
        self.assertTrue(
            all(record["contact_id"] == lin["id"] for record in lin_records)
        )

        zhou_records = self.assert_list_notes_success(
            self.db_path, zhou["id"], [note_zhou_1, note_zhou_2]
        )
        self.assertTrue(
            all(record["contact_id"] == zhou["id"] for record in zhou_records)
        )

        # 两人的备注编号集合互不相交
        lin_note_ids = {record["id"] for record in lin_records}
        zhou_note_ids = {record["id"] for record in zhou_records}
        self.assertTrue(lin_note_ids.isdisjoint(zhou_note_ids))

        # 追加备注不改变联系人资料与数量
        self.assert_company_list(self.db_path, LIN_COMPANY, [lin])
        self.assert_company_list(self.db_path, ZHOU_COMPANY, [zhou])

    def test_padded_and_leading_zero_ids_target_same_contact(self):
        lin, zhou = self.seed_two_contacts()

        # add-note：编号带首尾空白和前导零仍指向林宁
        for raw_id in (
            f"  00{lin['id']}  ",
            f"\t0{lin['id']}\t",
            f" \t000{lin['id']} \t",
        ):
            with self.subTest(raw_id=raw_id):
                record = self.assert_add_note_success(
                    self.add_note(self.db_path, raw_id, "  通过补零编号追加的备注  "),
                    lin["id"],
                    "通过补零编号追加的备注",
                )
                self.assertEqual(record["contact_id"], lin["id"])

        # list-notes：同样的编号写法查询到全部三条备注，且都归属林宁
        for raw_id in (
            f"  00{lin['id']}  ",
            f"\t0{lin['id']}\t",
            f" \t000{lin['id']} \t",
        ):
            with self.subTest(raw_id=raw_id):
                result = self.list_notes(self.db_path, raw_id)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")
                records = json.loads(result.stdout.decode("utf-8"))
                self.assertEqual(len(records), 3)
                self.assertTrue(
                    all(record["contact_id"] == lin["id"] for record in records)
                )
                self.assertEqual(
                    [record["id"] for record in records],
                    sorted(record["id"] for record in records),
                )

        # 周岚没有备注，且编号规范化不影响两人的资料与数量
        self.assert_list_notes_success(self.db_path, zhou["id"], [])
        self.assert_contacts_unchanged(lin, zhou)

    # ---- 编号校验（两个入口一致） ----

    def test_both_note_commands_reject_invalid_ids_without_changes(self):
        lin, zhou = self.seed_two_contacts()
        note = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], LIN_NOTE_RAW_1),
            lin["id"],
            LIN_NOTE_RAW_1.strip(),
        )
        notes_before = self.notes_snapshot()
        self.assertEqual(notes_before[0], [note])

        for raw_id in INVALID_IDS:
            for command, cli_args in (
                ("add-note", ["add-note", "--id", raw_id, "--text", "不应写入的备注"]),
                ("list-notes", ["list-notes", "--id", raw_id]),
            ):
                with self.subTest(command=command, raw_id=raw_id[:8]):
                    result = self.run_crm(self.db_path, *cli_args)
                    self.assert_rejected(result, ID_ERROR_LINE)

        # 所有失败之后联系人与备注仍保持失败前的状态
        self.assert_contacts_unchanged(lin, zhou)
        self.assert_notes_unchanged(notes_before)

    def test_add_note_rejects_empty_or_blank_text_without_changes(self):
        lin, zhou = self.seed_two_contacts()
        notes_before = self.notes_snapshot()

        for text in BLANK_TEXTS:
            with self.subTest(text=repr(text)):
                result = self.add_note(self.db_path, lin["id"], text)
                self.assert_rejected(result, TEXT_ERROR_LINE)

        self.assert_contacts_unchanged(lin, zhou)
        self.assert_notes_unchanged(notes_before)

    def test_add_note_reports_id_error_before_text_error(self):
        lin, zhou = self.seed_two_contacts()
        notes_before = self.notes_snapshot()

        # 编号与正文同时无效时只报告编号错误
        for raw_id, text in (
            ("0", "   "),
            ("abc", ""),
            ("9" * 5000, " \n\t "),
            ("-1", "\t\t"),
        ):
            with self.subTest(raw_id=raw_id[:8], text=repr(text)):
                result = self.add_note(self.db_path, raw_id, text)
                self.assert_rejected(result, ID_ERROR_LINE)

        self.assert_contacts_unchanged(lin, zhou)
        self.assert_notes_unchanged(notes_before)

    # ---- 联系人不存在 / 数据库父目录缺失 ----

    def test_both_note_commands_report_not_found_for_unknown_id(self):
        lin, zhou = self.seed_two_contacts()
        notes_before = self.notes_snapshot()

        # 合法编号 99 在样例数据库中不存在
        result_add = self.add_note(self.db_path, 99, "不会写入的备注")
        self.assert_rejected(result_add, NOT_FOUND_LINE)

        result_list = self.list_notes(self.db_path, 99)
        self.assert_rejected(result_list, NOT_FOUND_LINE)

        # 失败后联系人与备注均不变
        self.assert_contacts_unchanged(lin, zhou)
        self.assert_notes_unchanged(notes_before)

    def test_both_note_commands_reject_missing_parent_directory(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result_add = self.run_crm(
            fresh_db, "add-note", "--id", "1", "--text", "不应写入的备注"
        )
        self.assert_rejected(result_add, DB_ERROR_LINE)

        result_list = self.run_crm(fresh_db, "list-notes", "--id", "1")
        self.assert_rejected(result_list, DB_ERROR_LINE)

        # 父目录与数据库文件都不应被创建
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- 数据库文件的创建边界 ----

    def test_invalid_inputs_do_not_create_missing_database(self):
        index = 0

        # 两个入口的无效编号均不得创建数据库
        for raw_id in INVALID_IDS:
            for command, cli_args in (
                ("add-note", ["add-note", "--id", raw_id, "--text", "x"]),
                ("list-notes", ["list-notes", "--id", raw_id]),
            ):
                fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
                index += 1
                with self.subTest(command=command, raw_id=raw_id[:8]):
                    self.assertFalse(fresh_db.exists())
                    result = self.run_crm(fresh_db, *cli_args)
                    self.assert_rejected(result, ID_ERROR_LINE)
                    self.assertFalse(fresh_db.exists())
                    self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

        # add-note 正文为空或纯空白时不得创建数据库
        for text in BLANK_TEXTS:
            fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
            index += 1
            with self.subTest(text=repr(text)):
                self.assertFalse(fresh_db.exists())
                result = self.run_crm(
                    fresh_db, "add-note", "--id", "1", "--text", text
                )
                self.assert_rejected(result, TEXT_ERROR_LINE)
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

        # 编号与正文同时无效时同样不得创建数据库
        for raw_id, text in (("0", "   "), ("abc", "")):
            fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
            index += 1
            with self.subTest(raw_id=raw_id):
                self.assertFalse(fresh_db.exists())
                result = self.run_crm(
                    fresh_db, "add-note", "--id", raw_id, "--text", text
                )
                self.assert_rejected(result, ID_ERROR_LINE)
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

        # 父目录缺失本身不得导致目录或文件被创建
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "fresh.sqlite3"
        self.assertFalse(fresh_db.exists())
        self.run_crm(fresh_db, "add-note", "--id", "1", "--text", "x")
        self.run_crm(fresh_db, "list-notes", "--id", "1")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_valid_params_with_unknown_contact_leave_initialized_empty_database(self):
        # add-note：参数合法、父目录存在、联系人不存在 → 保留已初始化的空库
        add_db = self.tmpdir / "add-note-empty.sqlite3"
        self.assertFalse(add_db.exists())
        result_add = self.run_crm(
            add_db, "add-note", "--id", "99", "--text", "不应写入的备注"
        )
        self.assert_rejected(result_add, NOT_FOUND_LINE)
        self.assertTrue(add_db.exists())

        # list-notes：同样保留空库
        list_db = self.tmpdir / "list-notes-empty.sqlite3"
        self.assertFalse(list_db.exists())
        result_list = self.run_crm(list_db, "list-notes", "--id", "99")
        self.assert_rejected(result_list, NOT_FOUND_LINE)
        self.assertTrue(list_db.exists())

        # 两个库都已建好 contacts/notes 表且均为空，后续查询返回空结果
        for db_path in (add_db, list_db):
            with self.subTest(db_path=db_path.name):
                with sqlite3.connect(db_path) as conn:
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
                self.assert_company_list(db_path, LIN_COMPANY, [])


if __name__ == "__main__":
    unittest.main()
