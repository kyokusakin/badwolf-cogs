import unittest

from applicationreview.rules import can_reject, is_application_message, is_approved


class ApplicationMessageTests(unittest.TestCase):
    def test_accepts_exact_application(self):
        self.assertTrue(is_application_message("申請：加入活動\n理由：想參加"))
        self.assertTrue(is_application_message("申請：加入活動\r\n理由：想參加"))

    def test_requires_two_nonempty_labeled_lines(self):
        invalid_messages = (
            "申請：\n理由：想參加",
            "申請：加入活動\n理由：   ",
            "申請:加入活動\n理由:想參加",
            "申請：加入活動\n理由：想參加\n其他：內容",
        )
        for content in invalid_messages:
            with self.subTest(content=content):
                self.assertFalse(is_application_message(content))


class ReviewerPermissionTests(unittest.TestCase):
    def test_allows_administrator_or_channel_manager(self):
        self.assertTrue(can_reject(administrator=True, manage_channels=False))
        self.assertTrue(can_reject(administrator=False, manage_channels=True))
        self.assertFalse(can_reject(administrator=False, manage_channels=False))


class ApprovalRuleTests(unittest.TestCase):
    def test_requires_strictly_more_approvals_than_oppositions(self):
        self.assertTrue(is_approved(approvals=1, oppositions=0))
        self.assertTrue(is_approved(approvals=3, oppositions=2))
        self.assertFalse(is_approved(approvals=0, oppositions=0))
        self.assertFalse(is_approved(approvals=2, oppositions=2))
        self.assertFalse(is_approved(approvals=1, oppositions=2))


if __name__ == "__main__":
    unittest.main()
