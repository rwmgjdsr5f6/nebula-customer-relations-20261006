"""crm.py update-email 改成他人相同邮箱时保留编号与备注的回归测试。

围绕“改邮箱只改邮箱，编号归属与备注不受影响”这一既有行为，从公开命令行
输入到返回结果展开端到端核对：

- 用 add 在临时 SQLite 文件中新建星河科技的林宁、许禾与远帆咨询的周岚，
  邮箱分别为 lin@example.test、xu@example.test、Zhou@example.test，
  以各次 add 返回的实际编号为准（不预设自增编号），再用 add-note 依次
  给林宁追加“首次联系”、给周岚追加“确认资料”、再次给林宁追加
  “首次联系”，保留 add-note 返回的完整备注 JSON（id/contact_id/text）；
- update-email 用带前导零与首尾空格的林宁编号提交，新邮箱为首尾带空格的
  “  Zhou@example.test  ”时，退出码 0、标准错误为空，标准输出是更新后的
  完整联系人 JSON，仅 email 变为去掉首尾空白并保留大小写的
  Zhou@example.test，编号、姓名、公司保持原值；
- 随后以独立命令调用 get 与 list-notes：联系人资料与更新结果一致，
  林宁原编号下的两条备注按备注编号升序返回，与两次 add-note 的输出
  逐字段一致（两条“首次联系”正文相同但编号不同，可发现重复记录被
  合并的回归）；原周岚的资料与备注保持原样；许禾资料不变且备注为空
  数组（可发现备注串到其他联系人的回归）；
- 林宁更新后的邮箱与周岚相同：list --email 跨公司返回两名不同编号的
  联系人（更新后的林宁与原周岚），按联系人编号升序，联系人不被合并；
  对林宁再次提交相同邮箱同样成功，联系人与备注的数量和内容均不改变
  （可发现备注丢失或重复写入）；按小写 zhou@example.test 精确筛选
  返回空数组，说明大小写被原样保留；
- 用同样已带备注的数据验证更新被拒绝时的失败隔离：编号 0 配合合法
  邮箱只报 id: must be a positive integer，合法编号配合 abc 只报
  email: invalid email address，未使用的正整数编号配合合法邮箱只报
  id: contact not found，编号 0 与邮箱 abc 同时传入时只报告编号错误；
  上述失败均退出 2、标准输出为空、标准错误仅含对应一行及结尾换行，
  失败后三个联系人的资料与全部备注与失败前完全一致。

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
ZHOU_EMAIL = "Zhou@example.test"
ZHOU_EMAIL_PADDED = "  Zhou@example.test  "

XINGHE_COMPANY = "星河科技"
YUANFAN_COMPANY = "远帆咨询"

LIN_NOTE_TEXT = "首次联系"
ZHOU_NOTE_TEXT = "确认资料"

ID_ERROR_LINE = "id: must be a positive integer"
EMAIL_ERROR_LINE = "email: invalid email address"
NOT_FOUND_LINE = "id: contact not found"


class UpdateEmailPreservesNotesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    # ---- 命令执行与解析辅助 ----

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, name, email, company):
        """add 成功时返回解析后的联系人字典。"""
        result = self.run_crm(
            self.db_path,
            "add",
            "--name",
            name,
            "--email",
            email,
            "--company",
            company,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record["name"], name)
        self.assertEqual(record["email"], email)
        self.assertEqual(record["company"], company)
        return record

    def add_note(self, contact_id, text):
        """add-note 成功时返回解析后的完整备注字典。"""
        result = self.run_crm(
            self.db_path, "add-note", "--id", str(contact_id), "--text", text
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "contact_id", "text"})
        return record

    def update_email(self, contact_id, email):
        return self.run_crm(
            self.db_path,
            "update-email",
            "--id",
            str(contact_id),
            "--email",
            email,
        )

    def get_contact(self, contact_id):
        """get 成功时返回解析后的联系人字典。"""
        result = self.run_crm(self.db_path, "get", "--id", str(contact_id))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def list_notes(self, contact_id):
        """list-notes 成功时返回解析后的备注数组。"""
        result = self.run_crm(self.db_path, "list-notes", "--id", str(contact_id))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def list_all(self):
        """list（不带筛选）成功时返回全部联系人，按编号升序。"""
        result = self.run_crm(self.db_path, "list")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(
            [record["id"] for record in records],
            sorted(record["id"] for record in records),
        )
        return records

    def list_by_email(self, email):
        """list --email（精确匹配，区分大小写）成功时返回联系人数组。"""
        result = self.run_crm(self.db_path, "list", "--email", email)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8"))

    def assert_rejected(self, result, expected_stderr_line):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误恰为单行加换行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    # ---- 固定合成资料 ----

    def seed_noted_contacts(self):
        """新建三名联系人并追加三条备注，返回全部 add/add-note 输出。

        联系人依次为林宁、许禾（星河科技）与周岚（远帆咨询）；周岚的邮箱
        为大写开头的 Zhou@example.test。备注依次为林宁“首次联系”、
        周岚“确认资料”、林宁“首次联系”。编号一律取各次命令的实际返回值，
        不依赖自增起始值。
        """
        lin = self.add_contact(LIN_NAME, LIN_EMAIL, XINGHE_COMPANY)
        xu = self.add_contact(XU_NAME, XU_EMAIL, XINGHE_COMPANY)
        zhou = self.add_contact(ZHOU_NAME, ZHOU_EMAIL, YUANFAN_COMPANY)
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])

        note_lin_first = self.add_note(lin["id"], LIN_NOTE_TEXT)
        note_zhou = self.add_note(zhou["id"], ZHOU_NOTE_TEXT)
        note_lin_second = self.add_note(lin["id"], LIN_NOTE_TEXT)

        self.assertEqual(
            note_lin_first,
            {"id": note_lin_first["id"], "contact_id": lin["id"], "text": LIN_NOTE_TEXT},
        )
        self.assertEqual(
            note_zhou,
            {"id": note_zhou["id"], "contact_id": zhou["id"], "text": ZHOU_NOTE_TEXT},
        )
        self.assertEqual(
            note_lin_second,
            {
                "id": note_lin_second["id"],
                "contact_id": lin["id"],
                "text": LIN_NOTE_TEXT,
            },
        )
        # 两条同文备注编号不同且全局按追加顺序递增（防合并的前提）
        self.assertNotEqual(note_lin_first["id"], note_lin_second["id"])
        self.assertLess(note_lin_first["id"], note_zhou["id"])
        self.assertLess(note_zhou["id"], note_lin_second["id"])

        return {
            "lin": lin,
            "xu": xu,
            "zhou": zhou,
            "note_lin_first": note_lin_first,
            "note_lin_second": note_lin_second,
            "note_zhou": note_zhou,
        }

    # ---- 全量状态快照（联系人资料 + 各联系人备注） ----

    def snapshot_state(self, contacts):
        """通过公开命令记录三个联系人当前的资料与全部备注。"""
        lin, xu, zhou = contacts
        return {
            "contacts": {
                lin["id"]: self.get_contact(lin["id"]),
                xu["id"]: self.get_contact(xu["id"]),
                zhou["id"]: self.get_contact(zhou["id"]),
            },
            "notes": {
                lin["id"]: self.list_notes(lin["id"]),
                xu["id"]: self.list_notes(xu["id"]),
                zhou["id"]: self.list_notes(zhou["id"]),
            },
            "all_contacts": self.list_all(),
        }

    def assert_state_equals(self, expected):
        """重新查询并断言资料、备注与全部联系人列表与快照逐字段一致。"""
        for contact_id, contact_record in expected["contacts"].items():
            self.assertEqual(self.get_contact(contact_id), contact_record)
        for contact_id, note_records in expected["notes"].items():
            self.assertEqual(self.list_notes(contact_id), note_records)
        self.assertEqual(self.list_all(), expected["all_contacts"])

    # ---- 改邮箱成功：邮箱变成与周岚相同，编号、姓名、备注原样保留 ----

    def test_update_email_to_another_contacts_email_preserves_id_and_notes(self):
        data = self.seed_noted_contacts()
        lin = data["lin"]
        xu = data["xu"]
        zhou = data["zhou"]
        note_lin_first = data["note_lin_first"]
        note_lin_second = data["note_lin_second"]
        note_zhou = data["note_zhou"]

        # 用带前导零与首尾空格的林宁编号提交，新邮箱首尾也带空白
        padded_lin_id = f"  00{lin['id']}  "
        result = self.update_email(padded_lin_id, ZHOU_EMAIL_PADDED)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        updated_lin = {
            "id": lin["id"],
            "name": LIN_NAME,
            "email": ZHOU_EMAIL,
            "company": XINGHE_COMPANY,
        }
        # 标准输出整体就是一行完整联系人 JSON：仅 email 改变，
        # 编号、姓名、公司保持原值，邮箱首尾空白被清除而大小写保留
        self.assertEqual(
            result.stdout.decode("utf-8"),
            json.dumps(updated_lin, ensure_ascii=False) + "\n",
        )
        updated_record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(updated_record["id"], lin["id"])
        self.assertEqual(updated_record["name"], lin["name"])
        self.assertEqual(updated_record["company"], lin["company"])
        self.assertEqual(updated_record["email"], ZHOU_EMAIL)
        self.assertNotEqual(updated_record["email"], LIN_EMAIL)

        # 独立调用 get：联系人资料与更新结果逐字段一致
        self.assertEqual(self.get_contact(lin["id"]), updated_lin)
        self.assertEqual(self.get_contact(lin["id"]), updated_record)

        # 独立调用 list-notes：林宁原编号下的两条备注按备注编号升序返回，
        # 与 add-note 返回的 id/contact_id/text 逐字段一致；
        # 两条正文同为“首次联系”但编号不同
        lin_notes = self.list_notes(lin["id"])
        self.assertEqual(lin_notes, [note_lin_first, note_lin_second])
        self.assertEqual(
            [note["id"] for note in lin_notes],
            sorted(note["id"] for note in lin_notes),
        )
        self.assertTrue(
            all(note["contact_id"] == lin["id"] for note in lin_notes)
        )
        self.assertEqual(
            [note["text"] for note in lin_notes],
            [LIN_NOTE_TEXT, LIN_NOTE_TEXT],
        )
        self.assertEqual(
            len({note["id"] for note in lin_notes}), len(lin_notes)
        )

        # 原周岚的资料与备注保持原样；许禾资料不变且备注为空数组
        self.assertEqual(self.get_contact(zhou["id"]), zhou)
        self.assertEqual(self.list_notes(zhou["id"]), [note_zhou])
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.list_notes(xu["id"]), [])

        # 相同邮箱不合并联系人：list --email 跨公司返回两个不同编号的
        # 联系人（更新后的林宁与原周岚），按编号升序，编号集合互不相同
        same_email_records = self.list_by_email(ZHOU_EMAIL)
        self.assertEqual(same_email_records, [updated_lin, zhou])
        self.assertEqual(
            [record["id"] for record in same_email_records],
            sorted(record["id"] for record in same_email_records),
        )
        self.assertEqual(
            len({record["id"] for record in same_email_records}),
            len(same_email_records),
        )
        self.assertEqual(
            {record["company"] for record in same_email_records},
            {XINGHE_COMPANY, YUANFAN_COMPANY},
        )

        # 邮箱精确匹配且区分大小写：小写写法筛不到任一联系人，
        # 说明大写 Z 被原样保留
        self.assertEqual(self.list_by_email(ZHOU_EMAIL.lower()), [])
        # 林宁的旧邮箱已无联系人使用
        self.assertEqual(self.list_by_email(LIN_EMAIL), [])

        # 再次提交相同邮箱仍成功：输出与上次完全一致
        repeat = self.update_email(lin["id"], ZHOU_EMAIL_PADDED)
        self.assertEqual(repeat.returncode, 0, repeat.stderr.decode("utf-8"))
        self.assertEqual(repeat.stderr, b"")
        self.assertEqual(
            repeat.stdout.decode("utf-8"),
            json.dumps(updated_lin, ensure_ascii=False) + "\n",
        )

        # 联系人仍是三名；联系人资料与全部备注的数量、内容均不改变：
        # 不合并、不丢备注、不重复写入、不串号
        all_contacts = self.list_all()
        self.assertEqual(all_contacts, [updated_lin, xu, zhou])
        self.assertEqual(len(all_contacts), 3)
        self.assertEqual(self.get_contact(lin["id"]), updated_lin)
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.get_contact(zhou["id"]), zhou)
        self.assertEqual(
            self.list_notes(lin["id"]), [note_lin_first, note_lin_second]
        )
        self.assertEqual(self.list_notes(zhou["id"]), [note_zhou])
        self.assertEqual(self.list_notes(xu["id"]), [])
        self.assertEqual(self.list_by_email(ZHOU_EMAIL), [updated_lin, zhou])

    # ---- 更新被拒绝：三个联系人的资料与全部备注保持失败前状态 ----

    def test_rejected_email_updates_leave_contacts_and_notes_unchanged(self):
        data = self.seed_noted_contacts()
        lin = data["lin"]
        xu = data["xu"]
        zhou = data["zhou"]

        contacts = (lin, xu, zhou)
        state_before = self.snapshot_state(contacts)

        # 取一个必然未使用的正整数编号（大于现有最大编号）
        unused_id = str(max(lin["id"], xu["id"], zhou["id"]) + 100)

        # (编号输入, 邮箱输入, 期望的标准错误单行)
        rejected_cases = [
            # 编号为 0，邮箱合法：只报告编号错误
            ("0", ZHOU_EMAIL, ID_ERROR_LINE),
            # 合法联系人编号配合非法邮箱 abc：只报告邮箱错误
            (str(lin["id"]), "abc", EMAIL_ERROR_LINE),
            # 未使用的正整数编号配合合法邮箱：联系人不存在
            (unused_id, ZHOU_EMAIL, NOT_FOUND_LINE),
            # 编号与邮箱同时无效时只报告编号错误
            ("0", "abc", ID_ERROR_LINE),
        ]

        for raw_id, email, expected_error in rejected_cases:
            with self.subTest(raw_id=raw_id, email=email):
                result = self.update_email(raw_id, email)
                self.assert_rejected(result, expected_error)

                # 每次失败后立即重新查询：三个联系人的资料、全部备注
                # 以及联系人总数逐字段保持失败前状态
                self.assert_state_equals(state_before)

        # 全部失败后再做一次显式核对：林宁邮箱仍为 lin@example.test 且
        # 两条同文备注均在原编号下且编号不变，周岚资料与备注原样，
        # 许禾资料不变且没有备注
        self.assertEqual(self.get_contact(lin["id"]), lin)
        self.assertEqual(self.get_contact(xu["id"]), xu)
        self.assertEqual(self.get_contact(zhou["id"]), zhou)
        self.assertEqual(
            self.list_notes(lin["id"]),
            [data["note_lin_first"], data["note_lin_second"]],
        )
        self.assertEqual(self.list_notes(zhou["id"]), [data["note_zhou"]])
        self.assertEqual(self.list_notes(xu["id"]), [])
        self.assertEqual(self.list_all(), [lin, xu, zhou])
        self.assertEqual(self.list_by_email(LIN_EMAIL), [lin])
        self.assertEqual(self.list_by_email(ZHOU_EMAIL), [zhou])


if __name__ == "__main__":
    unittest.main()
