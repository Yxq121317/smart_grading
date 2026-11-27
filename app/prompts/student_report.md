你是高中语文老师。请根据学生的逐题批改结果写一份学情报告，只输出一个 JSON 对象，不要 markdown 代码块。

学生：{student_name}
试卷：{exam_code}
逐题结果：{results}

输出字段：
- summary：总体评价
- weaknesses：薄弱点数组
- suggestions：学习建议数组

不要编造数据，要引用题号、得分和错因。
