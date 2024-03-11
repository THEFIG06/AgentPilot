# from langchain.chat_models import ChatOpenAI
from langchain_community.chat_models import ChatLiteLLM

from src.agent.base import Agent
# from src.gui.components.agent_settings import AgentSettings
from src.plugins.crewai.src.agent import Agent as CAIAgent
from src.plugins.crewai.src.task import Task as CAITask


class CrewAI_Agent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_key = 'crewai'
        # If all agents in a group have the same key, the corresponding context plugin will be used
        self.agent_object = None
        self.agent_task = None
        self.schema = [
            {
                'text': 'Role',
                'type': str,
                'label_width': 75,
                'width': 450,
                'default': '',
            },
            {
                'text': 'Goal',
                'type': str,
                'label_width': 75,
                'width': 450,
                'default': '',
            },
            {
                'text': 'Backstory',
                'type': str,
                'label_position': 'top',
                'label_width': 110,
                'width': 525,
                'num_lines': 4,
                'default': '',
            },
            {
                'text': 'Memory',
                'type': bool,
                'label_width': 75,
                'row_key': 'X',
                'default': False,
            },
            {
                'text': 'Allow delegation',
                'type': bool,
                'label_width': 125,
                # 'label_text_alignment': Qt.AlignRight,
                'row_key': 'X',
                'default': True,
            },
        ]

    # class CustomSchema(AgentSettings):
    #     def __init__(self, *args, **kwargs):
    #         super().__init__(*args, **kwargs)
    #
    #         self.pages['Chat']['Messages'].schema = [
    #             {
    #                 'text': 'Model',
    #                 'type': 'ModelComboBox',
    #                 'default': 'gpt-3.5-turbo',
    #                 'row_key': 0,
    #             },
    #             {
    #                 'text': 'Display markdown',
    #                 'type': bool,
    #                 'default': True,
    #                 'row_key': 0,
    #             },
    #             {
    #                 'text': 'Task',
    #                 'type': str,
    #                 'num_lines': 8,
    #                 'default': '',
    #                 'width': 520,
    #                 'label_position': 'top',
    #             },
    #             {
    #                 'text': 'Expected output',
    #                 'type': str,
    #                 'num_lines': 2,
    #                 'default': '',
    #                 'width': 520,
    #                 'label_position': 'top',
    #             },
    #         ]

    def load_agent(self):
        super().load_agent()

        model_name = self.config.get('context.model', 'gpt-3.5-turbo')
        model = (model_name, self.workflow.main.system.models.get_llm_parameters(model_name))

        llm = ChatLiteLLM(
          temperature=0.7,
          model_name=model_name,
        )  # todo link to model config

        tools = self.tools.values()
        self.agent_object = CAIAgent(
            # step_callback=self.step_callback,
            llm=llm,
            role=self.config.get('plugin.role', ''),
            goal=self.config.get('plugin.goal', ''),
            backstory=self.config.get('plugin.backstory', ''),
            memory=self.config.get('plugin.memory', True),
            allow_delegation=self.config.get('plugin.allow_delegation', True),
            tools=tools,
            response_callback=self.response_callback,
        )

        task_desc = self.system_message()
        expected_output = self.config.get('context.user_msg', '')
        self.agent_task = CAITask(
            description=task_desc,
            expected_output=expected_output,
            agent=self.agent_object,
        )

    def response_callback(self, role, message):
        self.workflow.main.new_sentence_signal.emit(self.member_id, message)
        self.workflow.save_message('assistant', message, self.member_id)
        pass

    # def response_callback(self, message):
    #     self.workflow.main.new_sentence_signal.emit(self.member_id, message)
    #     self.workflow.save_message('assistant', message, self.member_id)
    #     pass

    #
    # def stream(self, *args, **kwargs):
    #     pass
