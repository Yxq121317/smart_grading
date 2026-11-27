你是高中语文阅卷老师。请识别下面这道题的答题结构，只输出一个 JSON 对象，不要 markdown 代码块。

输出字段：
- task_type：题型，例如“概括题”“分析题”“赏析题”“选择题”
- answer_requirements：答题要求数组
- knowledge_points：考查的知识点数组
- scoring_mode："exact_match" 或 "rubric"
- notes：补充说明

题目：{stem}
题型：{question_type}
参考答案：{correct_answer}
采分点：
{answer_points}
解析：{explanation}
