def test_resolve_scope_uses_existing_helper(tmp_path):
    """限定范围检索不应因内部函数名写错而失败（回归：曾经引用了不存在的 _all_indexed_docs）。"""
    # 项目内：被测函数；只要它内部引用的辅助函数存在，空知识库也应正常返回空列表
    from app.tools.file_read_tool import resolve_scope

    matched, missing = resolve_scope([str(tmp_path / "不存在.md")])
    # 知识库里没有这篇文档：命中为空、未匹配列表里有它，且**没有抛异常**
    assert matched == []
    assert missing == [str(tmp_path / "不存在.md")]


def test_run_command_tool_schema_keeps_command_args(tmp_path):
    """run_command 的参数数组必须能正常传进工具（回归：参数名 args 被 LangChain 过滤掉）。

    现象：参数名如果叫 args，LangChain 生成入参模型时会把它当成 pydantic 的
    "可变位置参数占位字段"过滤掉，只留下 v__args；模型每次调用都收到
    "build_run_action() got an unexpected keyword argument 'v__args'"，然后反复重试，
    直到把 LangGraph 的 recursion_limit（默认 25 步）耗尽。
    """
    # 项目内：被测工具；它的 args_schema 由 @tool 按函数签名自动生成
    from app.tools.run_command_tool import run_command

    # 入参模型里必须有 command_args，且不能残留 pydantic 的合成字段
    fields = run_command.args_schema.model_fields
    assert "command_args" in fields
    assert "v__args" not in fields

    # 走一次完整 invoke：命令不在允许列表时应当返回正常的 FAIL 文案，
    # 而不是 "unexpected keyword argument" 这类工具调用层的错误
    result = run_command.invoke({
        "command": "definitely-not-allowed",
        "command_args": ["version"],
        "cwd": str(tmp_path),
    })
    assert "不在允许列表内" in result
    assert "unexpected keyword argument" not in result

