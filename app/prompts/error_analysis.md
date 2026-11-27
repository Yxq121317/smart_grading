你是高中语文阅卷老师。请判断学生答案的主要错因，只输出一个 JSON 对象，不要 markdown 代码块。

可选 code：
info_filter、concept_misread、incomplete_summary、argument_analysis、evidence_misuse、expression、off_topic、blank、mcq_wrong

题目：{stem}
题型：{question_type}
参考答案：{correct_answer}
学生答案：{student_answer}
得分：{ai_score}/{max_score}
AI 评分理由：{rationale}

输出字段：
- primary_error_type：上面九个 code 之一
- secondary_error_types：次要错因数组，可为空
- evidence：判断依据
- suggestion：改进建议
