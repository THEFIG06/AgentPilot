import time
import openai
from PySide6.QtWidgets import QMessageBox
from openai import OpenAI
from openai.types.beta import CodeInterpreterTool
from openai.types.beta.assistant_stream_event import ThreadMessageDelta

from src.gui.config import ConfigFields
from src.members.agent import Agent, AgentSettings
from src.utils.helpers import display_messagebox


class OpenAI_Assistant(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = OpenAI()

        # self.schema = [
        #     {
        #         'text': 'Code Interpreter',
        #         'type': bool,
        #         'default': True,
        #         'width': 175,
        #     },
        # ]
        # # self.extra_config = {
        # #     'assistant.id'
        # # }
        # self.instance_config = {
        #     'assistant_id': None,
        # }

        self.assistant = None

    # def load_agent(self):
    #     super().load_agent()
    #     # ADD CHECK FOR CHANGED CONFIG, IF INVALID, RECREATE ASSISTANT

    def find_assistant(self):  # todo rethink, maybe reintroduce instance config
        name = self.config.get('info.name', 'Assistant')
        instructions = self.system_message()
        model = self.config.get('chat.model', 'gpt-3.5-turbo')
        code_interpreter = self.config.get('plugin.code_interpreter', True)
        pass

        try:
            assistants = openai.beta.assistants.list(limit=100)

            for assistant in assistants.data:
                tools = assistant.tools
                has_ci = isinstance(tools, list) and len(tools) == 1 and isinstance(tools[0], CodeInterpreterTool)
                ci_match = has_ci == code_interpreter
                if assistant.name == name and \
                        assistant.instructions == instructions and \
                        assistant.model == model and \
                        ci_match:
                        # assistant.tools == (["type": "code_interpreter"] if code_interpreter else []):
                    pass
                    return assistant.id

            return None

        except Exception as e:
            raise e

    def initialize_assistant(self):
        if self.assistant is None:
            ass_id = self.find_assistant()
            if ass_id:
                self.assistant = self.client.beta.assistants.retrieve(ass_id)
            else:
                self.assistant = self.create_assistant()

    def create_assistant(self):
        name = self.config.get('info.name', 'Assistant')
        model_name = self.config.get('chat.model', 'gpt-3.5-turbo')
        system_msg = self.system_message()

        code_interpreter = self.config.get('plugin.Code Interpreter', True)
        tools = [] if not code_interpreter else [{"type": "code_interpreter"}]
        return openai.beta.assistants.create(
            name=name,
            instructions=system_msg,
            model=model_name,
            tools=tools,
        )

        # # self.update_instance_config('assistant_id', assistant.id)

    # MERGE INTO config
    # - IGNORE INSTANCE PARAMS WHEN update_agent_config IS CALLED
    # - IGNORE AGENT PARAMS WHEN update_instance_config IS CALLED
    # WHEN YOU MODIFY THE PLUGIN CONFIG, IT SHOULD RELOAD THE AGENT

    async def stream(self, *args, **kwargs):
        if self.assistant is None:
            self.initialize_assistant()

        messages = kwargs.get('messages', [])

        run = self.client.beta.threads.create_and_run(
            assistant_id=self.assistant.id,
            stream=True,
            thread={
                "messages": messages
            }
        )

        for event in run:
            if not isinstance(event, ThreadMessageDelta):
                continue
            chunk = event.data.delta.content[0].text.value
            yield 'assistant', chunk

            # msg = next((msg for msg in reversed(messages) if msg['role'] == 'user'), None)
        # new_msg = self.client.beta.threads.messages.create(
        #     thread_id=self.thread.id,
        #     role=msg['role'],
        #     content=msg['content'],
        # )
        # last_msg_id = new_msg.id
        #
        # run = self.client.beta.threads.runs.create(
        #     thread_id=self.thread.id,
        #     assistant_id=self.assistant.id
        # )
        #
        # self.wait_on_run(run, self.thread)
        #
        # # Retrieve all the messages added after our last user message
        # messages = self.client.beta.threads.messages.list(
        #     thread_id=self.thread.id, order="asc", after=last_msg_id
        # )
        # if len(messages.data) == 1:
        #     yield 'assistant', messages.data[0].content[0].text.value
        # elif len(messages.data) > 1:  # can it be?
        #     # for msg in messages where not the last one
        #     for msg in messages.data[:-1]:
        #         msg_content = msg.content[0].text.value
        #         self.workflow.save_message('assistant', msg_content)
        #     yield 'assistant', messages.data[-1].content[0].text.value  # todo - hacky - last msg is saved later
        # else:
        #     yield 'assistant', ''  # can this happen?

    # def wait_on_run(self, run, thread):
    #     while run.status == "queued" or run.status == "in_progress":
    #         run = self.client.beta.threads.runs.retrieve(
    #             thread_id=thread.id,
    #             run_id=run.id,
    #         )
    #         time.sleep(0.5)
    #     return run


class OAIAssistantSettings(AgentSettings):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages.pop('Files')
        info_widget = self.pages['Info']
        info_widget.widgets.append(self.Plugin_Fields(parent=info_widget))

    class Plugin_Fields(ConfigFields):
        def __init__(self, parent):
            super().__init__(parent=parent)
            self.parent = parent
            self.namespace = 'plugin'
            self.schema = [
                {
                    'text': 'Code Interpreter',
                    'type': bool,
                    'default': True,
                    'width': 175,
                },
            ]
