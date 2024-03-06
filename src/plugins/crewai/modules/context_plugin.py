import asyncio
from src.context.base import WorkflowBehaviour
from src.plugins.crewai.src.crew import Crew


class CrewAI_Workflow(WorkflowBehaviour):
    def __init__(self, workflow):
        super().__init__(workflow=workflow)
        self.group_key = 'crewai'
        self.crew = None

    def start(self):
        try:
            t = self.workflow.loop.create_task(self.run_crew())
            self.workflow.loop.run_until_complete(t)
        except Exception as e:
            raise e

    def stop(self):
        """Disable the default stop method"""
        pass
        # self.context.stop_requested = True
        # for member in self.context.members.values():
        #     if member.response_task is not None:
        #         member.response_task.cancel()

    async def run_crew(self):
        agents = [member.agent_object for member in self.workflow.members.values()]
        tasks = [member.agent_task for member in self.workflow.members.values()]
        self.crew = Crew(agents=agents, tasks=tasks)  # , step_callback=self.step_callback)
        self.crew.kickoff()

    def step_callback(self, callback_object):
        pass