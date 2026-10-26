"""A scripted chat model: replays fixed replies instead of calling a provider.

Used for the `demo://` model in the app and as the model in the test suite, so
the same task always takes the same steps.
"""

from __future__ import annotations

from typing import Any
import hashlib
import json

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def call(name: str, **args: Any) -> dict[str, Any]:
    """Shorthand for one tool call inside a scripted reply."""
    digest=hashlib.sha256(json.dumps(args,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
    return {"name": name, "args": args, "id": f"call_{name}_{digest}", "type": "tool_call"}


class ScriptedChatModel(BaseChatModel):
    """Answers with `script[n]`, where n is how many times it has already replied in this turn.

    Counting from the conversation (not from an internal counter) keeps it
    correct after a pause for approval or a restart: the position is read from
    the messages that are actually there.
    """

    script: list[AIMessage]
    product_demo: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":  # noqa: ARG002
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        # A turn starts at the user's message; notes the harness injects mid-turn do not restart it.
        last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not str(m.content).startswith("<verification>")), default=-1)
        replies_so_far = sum(1 for m in messages[last_human + 1 :] if isinstance(m, AIMessage))
        template = self.script[min(replies_so_far, len(self.script) - 1)]
        human_identity=str(messages[last_human].id or last_human) if last_human>=0 else 'initial'
        turn=hashlib.sha256(human_identity.encode()).hexdigest()[:12]
        reply = AIMessage(
            content=template.content,
            tool_calls=[{**c,'id':f'call_{turn}_{replies_so_far}_{index}'} for index,c in enumerate(template.tool_calls)],
            usage_metadata={"input_tokens": 1200, "output_tokens": 150, "total_tokens": 1350},
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


def demo_model() -> ScriptedChatModel:
    """The walkthrough behind `demo://`: plan, compute, write a file, report."""
    plan = [
        {"content": "خواندن دادهٔ فروش", "status": "in_progress"},
        {"content": "محاسبهٔ تغییر هفتگی", "status": "pending"},
        {"content": "نوشتن گزارش", "status": "pending"},
    ]
    done = [{**step, "status": "completed"} for step in plan]
    return ScriptedChatModel(
        product_demo=True,
        script=[
            AIMessage(content="", tool_calls=[call("write_todos", todos=plan)]),
            AIMessage(content="", tool_calls=[call("calculate", expression="(2840 - 3050) / 3050 * 100")]),
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "write_file",
                        file_path="/گزارش-نمایشی.md",
                        content="# گزارش نمایشی\n\nفروش این هفته ۲٬۸۴۰ میلیون تومان بود؛ ۶٫۹٪ کمتر از هفتهٔ قبل.\n",
                    )
                ],
            ),
            AIMessage(content="", tool_calls=[call("write_todos", todos=done)]),
            AIMessage(content="اجرای ثابتِ نمایشی پایان یافت. نتیجهٔ واقعی نوشتن را از رسید ابزار بررسی کنید؛ این متن به‌تنهایی تأیید ذخیره‌شدن فایل یا صحت پروژه نیست."),
        ]
    )


def task_demo_model(phase):
    """Honest product walkthrough: inspect/plan only, never claim a code fix."""
    steps=[{'content':'دیدن فهرست فایل‌های نسخهٔ کاری','status':'pending'},{'content':'بازبینی درخواست و انتخاب بررسی‌ها با مدل واقعی','status':'pending'}]
    if phase!='plan':steps=[{**step,'status':'completed'} for step in steps]
    return ScriptedChatModel(product_demo=True,script=[
        AIMessage(content='',tool_calls=[call('ls',path='/')]),
        AIMessage(content='',tool_calls=[call('write_todos',todos=steps)]),
        AIMessage(content='این اجرای ثابت نمایشی است. فهرست فایل‌ها بررسی و مراحل نمونه ثبت شد؛ هیچ اصلاح کد، نصب یا اجرای تستی انجام نشد. برای تحلیل و پیاده‌سازی واقعی، مدل خود را در تنظیمات انتخاب کنید.'),
    ])
