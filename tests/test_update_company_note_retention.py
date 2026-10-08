"""crm.py update-company 更新公司归属时保留备注的回归测试。

覆盖“围绕公司归属更新保留备注”这一既有行为的完整命令行流程：

- 用 add 建立三名联系人：林宁、许禾（星河科技）与周岚（远帆咨询），
  再依次给林宁、周岚、林宁追加“首次联系”“确认资料”“首次联系”，
  完整保留 add-note 返回的备注 JSON；
- update-company 把林宁的公司改成首尾带空格的“ 远帆咨询 ”时，退出码 0、
  标准错误为空，标准输出是完整联系人 JSON，仅 company 被清理为“远帆咨询”，
  编号、姓名和邮箱保持原值；
- 更新后通过全新的命令调用独立查询 list-notes：林宁的两条备注按备注编号
  升序返回，与追加时的 id/contact_id/text 完全一致（重复正文仍是两条独立
  记录，不会被合并）；周岚的备注保持原样；许禾返回空数组；
- 按公司查询时星河科技只剩许禾，远帆咨询包含林宁和周岚并按联系人编号
  升序排列；再次把林宁更新为相同公司仍成功，联系人与备注的数量和内容
  均不改变；
- 更新被拒绝时（编号为 0、合法编号配合纯空白公司、编号 99 不存在、
  编号与公司同时无效）均退出 2、标准输出为空、标准错误仅含对应一行及
  结尾换行，且编号与公司同时无效时只报告编号错误；失败后重新查询，
  三名联系人的资料与全部备注与失败前完全一致，备注不会丢失、重复记录
  不会被合并、备注也不会串到其他联系人。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

LIN_NAME = "林宁"
LIN_EMAIL = "lin@example.test"

XU_NAME = "许禾"
XU_EMAIL = "xu@example.test"

ZHOU_NAME = "周岚"
ZHOU_EMAIL = "zhou@example.test"

XINGHE_COMPANY = "星河科技"
YUANFAN_COMPANY = "远帆咨询"
YUANFAN_COMPANY_PADDED = "  远帆咨询  "

FIRST_CONTACT_TEXT = "首次联系"
CONFIRM_TEXT = "确认资料"

ID_ERROR_LINE = "id: must be a positive integer"
COMPANY_ERROR_LINE = "company: must not be empty"
NOT_FOUND_LINE = "id: contact not found"

# 不存在的合法联系人编号（样例库只有三名联系人）
UNKNOWN_ID = "99"

# update-company 被拒绝的参数组合：(编号, 公司) → 期望的标准错误行
REJECTED_CASES = [
    # 编号为 0
    (("0", YUANFAN_COMPANY), ID_ERROR_LINE),
    # 合法联系人编号配合纯空白公司（多种空白写法）
    ((None, "   "), COMPANY_ERROR_LINE),
    ((None, "\t\t"), COMPANY_ERROR_LINE),
    ((None, " \n\t "), COMPANY_ERROR_LINE),
    # 合法编号 99 在样例库中不存在
    ((UNKNOWN_ID, YUANFAN_COMPANY), NOT_FOUND_LINE),
    # 编号与公司同时无效时只报告编号错误
    (("0", "   "), ID_ERROR_LINE),
]


class UpdateCompanyNoteRetentionTestCase(unittest.TestCase):
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

    def update_company(self, db_path, contact_id, company):
        return self.run_crm(
            db_path, "update-company", "--id", str(contact_id), "--company", company
        )

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    def list_all(self, db_path):
        return self.run_crm(db_path, "list")

    # ---- 断言辅助 ----

    def assert_add_contact_success(self, result, expected):
        """断言 add 成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertGreater(record["id"], 0)
        self.assertEqual(record, expected)
        return record

    def assert_add_note_success(self, result, contact_id, expected_text):
        """断言 add-note 成功并返回解析后的完整备注字典。"""
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

    def assert_update_rejected(self, result, expected_stderr_line):
        """断言 update-company 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        # 仅含对应一行及结尾换行，不多不少
        self.assertEqual(stderr_text, expected_stderr_line + "\n")
        self.assertNotIn(b"Traceback", result.stderr)

    # ---- 固定合成数据 ----

    def seed_noted_contacts(self):
        """建立三名联系人并按指定顺序追加三条备注。

        返回 (contacts, notes)：contacts 为姓名到联系人 JSON 字典的映射，
        notes 为联系人编号到追加时返回的完整备注字典列表的映射。
        """
        lin = self.assert_add_contact_success(
            self.add_contact(self.db_path, LIN_NAME, LIN_EMAIL, XINGHE_COMPANY),
            {
                "id": 1,
                "name": LIN_NAME,
                "email": LIN_EMAIL,
                "company": XINGHE_COMPANY,
            },
        )
        xu = self.assert_add_contact_success(
            self.add_contact(self.db_path, XU_NAME, XU_EMAIL, XINGHE_COMPANY),
            {
                "id": 2,
                "name": XU_NAME,
                "email": XU_EMAIL,
                "company": XINGHE_COMPANY,
            },
        )
        zhou = self.assert_add_contact_success(
            self.add_contact(self.db_path, ZHOU_NAME, ZHOU_EMAIL, YUANFAN_COMPANY),
            {
                "id": 3,
                "name": ZHOU_NAME,
                "email": ZHOU_EMAIL,
                "company": YUANFAN_COMPANY,
            },
        )
        self.assertEqual([lin["id"], xu["id"], zhou["id"]], [1, 2, 3])

        # 依次给林宁、周岚、林宁追加备注；林宁两次正文完全相同
        note_lin_1 = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], FIRST_CONTACT_TEXT),
            lin["id"],
            FIRST_CONTACT_TEXT,
        )
        note_zhou_1 = self.assert_add_note_success(
            self.add_note(self.db_path, zhou["id"], CONFIRM_TEXT),
            zhou["id"],
            CONFIRM_TEXT,
        )
        note_lin_2 = self.assert_add_note_success(
            self.add_note(self.db_path, lin["id"], FIRST_CONTACT_TEXT),
            lin["id"],
            FIRST_CONTACT_TEXT,
        )

        # 备注编号按追加顺序严格递增
        self.assertLess(note_lin_1["id"], note_zhou_1["id"])
        self.assertLess(note_zhou_1["id"], note_lin_2["id"])
        # 相同正文仍是两条独立记录，没有被合并
        self.assertNotEqual(note_lin_1["id"], note_lin_2["id"])

        contacts = {"lin": lin, "xu": xu, "zhou": zhou}
        notes = {
            lin["id"]: [note_lin_1, note_lin_2],
            xu["id"]: [],
            zhou["id"]: [note_zhou_1],
        }
        return contacts, notes

    def assert_notes_state(self, notes):
        """逐个联系人重新查询备注，并与给定状态（含顺序）完全一致。"""
        all_ids = set()
        for contact_id, expected in notes.items():
            records = self.assert_list_notes_success(
                self.db_path, contact_id, expected
            )
            # 必须按备注编号升序
            self.assertEqual(
                [record["id"] for record in records],
                sorted(record["id"] for record in records),
            )
            # 每条备注都归属当前联系人，不会串到其他联系人
            self.assertTrue(
                all(record["contact_id"] == contact_id for record in records)
            )
            # 不同联系人的备注编号集合互不相交
            current_ids = {record["id"] for record in records}
            self.assertTrue(all_ids.isdisjoint(current_ids))
            all_ids.update(current_ids)
        return all_ids

    def snapshot_state(self, contacts, notes):
        """通过公开命令记录三名联系人与全部备注的完整状态。"""
        contact_snapshot = {}
        for key, contact in contacts.items():
            result = self.get_contact(self.db_path, contact["id"])
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            contact_snapshot[key] = json.loads(result.stdout.decode("utf-8"))

        notes_snapshot = {}
        for contact_id in notes:
            result = self.list_notes(self.db_path, contact_id)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            notes_snapshot[contact_id] = json.loads(result.stdout.decode("utf-8"))

        list_result = self.list_all(self.db_path)
        self.assertEqual(list_result.returncode, 0, list_result.stderr.decode("utf-8"))
        self.assertEqual(list_result.stderr, b"")

        return contact_snapshot, notes_snapshot

    def assert_state_equals_snapshot(self, contacts, notes, snapshot):
        """失败后重新查询：三名联系人资料与全部备注与快照完全一致。"""
        contact_snapshot, notes_snapshot = snapshot

        # 逐个 get：资料逐字段不变
        for key, contact in contacts.items():
            result = self.get_contact(self.db_path, contact["id"])
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            self.assertEqual(
                json.loads(result.stdout.decode("utf-8")), contact_snapshot[key]
            )

        # 全部联系人仍为三条且按编号升序，没有新增或丢失
        list_result = self.list_all(self.db_path)
        self.assertEqual(list_result.returncode, 0, list_result.stderr.decode("utf-8"))
        self.assertEqual(list_result.stderr, b"")
        all_records = json.loads(list_result.stdout.decode("utf-8"))
        self.assertEqual(
            all_records,
            [contact_snapshot[key] for key in ("lin", "xu", "zhou")],
        )
        self.assertEqual(
            [record["id"] for record in all_records],
            sorted(record["id"] for record in all_records),
        )

        # 全部备注（含数量、编号、归属、正文、顺序）不变
        for contact_id, expected_records in notes.items():
            self.assertEqual(expected_records, notes_snapshot[contact_id])
        self.assert_notes_state(notes)

    # ---- 公司归属更新成功时保留备注 ----

    def test_update_company_moves_contact_and_preserves_all_notes(self):
        contacts, notes = self.seed_noted_contacts()
        lin, xu, zhou = contacts["lin"], contacts["xu"], contacts["zhou"]

        # 把林宁的公司更新为首尾带空格的“ 远帆咨询  ”
        result = self.update_company(
            self.db_path, lin["id"], YUANFAN_COMPANY_PADDED
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        updated_lin = json.loads(result.stdout.decode("utf-8"))

        # 标准输出是完整联系人 JSON，仅 company 变为清理后的“远帆咨询”
        self.assertIsInstance(updated_lin, dict)
        self.assertEqual(set(updated_lin.keys()), {"id", "name", "email", "company"})
        self.assertEqual(
            updated_lin,
            {
                "id": lin["id"],
                "name": LIN_NAME,
                "email": LIN_EMAIL,
                "company": YUANFAN_COMPANY,
            },
        )
        self.assertEqual(updated_lin["id"], lin["id"])
        self.assertEqual(updated_lin["name"], lin["name"])
        self.assertEqual(updated_lin["email"], lin["email"])
        self.assertEqual(updated_lin["company"], YUANFAN_COMPANY)

        # 独立命令重新查询备注：林宁的两条备注按编号升序，与追加时返回的
        # 完整备注 JSON 逐条一致；周岚的备注保持原样；许禾仍为空数组
        self.assert_notes_state(notes)

        # 按公司查询：星河科技只剩许禾
        xinghe_result = self.list_company(self.db_path, XINGHE_COMPANY)
        self.assertEqual(xinghe_result.returncode, 0, xinghe_result.stderr.decode("utf-8"))
        self.assertEqual(xinghe_result.stderr, b"")
        self.assertEqual(json.loads(xinghe_result.stdout.decode("utf-8")), [xu])

        # 远帆咨询包含林宁和周岚，按联系人编号升序
        yuanfan_result = self.list_company(self.db_path, YUANFAN_COMPANY)
        self.assertEqual(
            yuanfan_result.returncode, 0, yuanfan_result.stderr.decode("utf-8")
        )
        self.assertEqual(yuanfan_result.stderr, b"")
        yuanfan_records = json.loads(yuanfan_result.stdout.decode("utf-8"))
        self.assertEqual(yuanfan_records, [updated_lin, zhou])
        self.assertEqual(
            [record["id"] for record in yuanfan_records],
            sorted(record["id"] for record in yuanfan_records),
        )

        # 再次更新为相同公司仍成功，输出与上次更新结果一致
        repeat = self.update_company(self.db_path, lin["id"], YUANFAN_COMPANY)
        self.assertEqual(repeat.returncode, 0, repeat.stderr.decode("utf-8"))
        self.assertEqual(repeat.stderr, b"")
        self.assertEqual(
            json.loads(repeat.stdout.decode("utf-8")), updated_lin
        )

        # 联系人数量与资料不变
        self.assertEqual(
            json.loads(self.list_all(self.db_path).stdout.decode("utf-8")),
            [updated_lin, xu, zhou],
        )
        self.assertEqual(
            json.loads(
                self.list_company(self.db_path, XINGHE_COMPANY).stdout.decode("utf-8")
            ),
            [xu],
        )
        self.assertEqual(
            json.loads(
                self.list_company(self.db_path, YUANFAN_COMPANY).stdout.decode("utf-8")
            ),
            [updated_lin, zhou],
        )

        # 备注数量与内容均不改变（两条相同正文的备注仍各自独立存在）
        self.assert_notes_state(notes)
        self.assertEqual(len(notes[lin["id"]]), 2)
        self.assertEqual(len(notes[zhou["id"]]), 1)
        self.assertEqual(notes[xu["id"]], [])

    # ---- 更新被拒绝时保留联系人和全部备注 ----

    def test_rejected_updates_keep_contacts_and_all_notes(self):
        contacts, notes = self.seed_noted_contacts()
        lin = contacts["lin"]

        # 先用已带备注的数据完成一次成功归属更新，再在更新后的状态上
        # 验证各类拒绝都不会改变资料与备注
        moved = self.update_company(
            self.db_path, lin["id"], YUANFAN_COMPANY_PADDED
        )
        self.assertEqual(moved.returncode, 0, moved.stderr.decode("utf-8"))
        self.assertEqual(moved.stderr, b"")
        moved_lin = json.loads(moved.stdout.decode("utf-8"))
        self.assertEqual(moved_lin["company"], YUANFAN_COMPANY)
        contacts["lin"] = moved_lin

        snapshot = self.snapshot_state(contacts, notes)

        # 快照中林宁的两条备注、周岚的一条备注都已随公司归属保留下来
        self.assertEqual(len(notes[lin["id"]]), 2)
        self.assertEqual(len(notes[contacts["zhou"]["id"]]), 1)

        for (raw_id, company), expected_line in REJECTED_CASES:
            # None 表示使用林宁的合法联系人编号
            contact_id = str(lin["id"]) if raw_id is None else raw_id
            with self.subTest(contact_id=contact_id, company=repr(company)):
                result = self.update_company(self.db_path, contact_id, company)
                self.assert_update_rejected(result, expected_line)

                # 每次失败之后三名联系人的资料和全部备注都与失败前一致
                self.assert_state_equals_snapshot(contacts, notes, snapshot)


if __name__ == "__main__":
    unittest.main()
