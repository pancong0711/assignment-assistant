"""M5 成绩管理（roster）——见 grouping.py 与 docs/05-D17/D18。"""

from .grouping import (DEFAULT_GROUP_CFG, PENALTY_TAGS, RANDOM_GROUP, norm_tag,
                       merge_scores, read_score_xlsx, tag_students,
                       tag_summary, tagged_xlsx)

__all__ = ["DEFAULT_GROUP_CFG", "PENALTY_TAGS", "RANDOM_GROUP", "norm_tag",
           "merge_scores", "read_score_xlsx", "tag_students", "tag_summary",
           "tagged_xlsx"]
