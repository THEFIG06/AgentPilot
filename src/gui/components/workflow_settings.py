import json
import sqlite3
from abc import abstractmethod
from functools import partial

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import Qt, QPen, QColor, QBrush, QPixmap, QPainter, QPainterPath, QCursor, QRadialGradient
from PySide6.QtWidgets import QWidget, QGraphicsScene, QPushButton, QGraphicsEllipseItem, QGraphicsItem, QGraphicsView, \
    QMessageBox, QGraphicsPathItem, QStackedLayout, QMenu, QInputDialog

from src.gui.components.config import ConfigWidget, CVBoxLayout, CHBoxLayout
# from src.gui.components.group_settings import ConnectionLine, ConnectionPoint, TemporaryConnectionLine

from src.gui.widgets.base import IconButton, ToggleButton, find_main_widget, colorize_pixmap, ListDialog
from src.members.agent import AgentSettings
from src.utils import sql
from src.utils.helpers import path_to_pixmap, display_messagebox, block_signals


class WorkflowSettings(ConfigWidget):
    def __init__(self, parent, **kwargs):
        super().__init__(parent)
        self.main = find_main_widget(self)
        self.compact_mode = kwargs.get('compact_mode', False)  # For use with composite agents

        self.members_in_view = {}  # id: member
        self.lines = {}  # (member_id, inp_member_id): line

        self.new_line = None
        self.new_agent = None

        self.layout = CVBoxLayout(self)
        self.workflow_buttons = WorkflowButtonsWidget(parent=self)
        # self.workflow_buttons.btn_add.clicked.connect(self.add_item)
        # self.workflow_buttons.btn_del.clicked.connect(self.delete_item)

        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 500, 200)
        self.scene.selectionChanged.connect(self.on_selection_changed)

        self.view = CustomGraphicsView(self.scene, self)

        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFixedHeight(200)

        self.compact_mode_back_button = self.CompactModeBackButton(parent=self)
        self.member_config_widget = self.DynamicMemberConfigWidget(parent=self)

        self.user_bubble = FixedUserBubble(self)
        self.scene.addItem(self.user_bubble)

        self.layout.addWidget(self.workflow_buttons)
        self.layout.addWidget(self.view)
        self.layout.addWidget(self.compact_mode_back_button)
        self.layout.addWidget(self.member_config_widget)
        self.layout.addStretch(1)

        # self.compact_mode_back_button.hide()

    class CompactModeBackButton(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.parent = parent
            self.layout = CHBoxLayout(self)
            self.btn_back = IconButton(
                parent=self,
                icon_path=':/resources/icon-back.png',
                tooltip='Back',
                size=18,
                text='Back to workflow'
            )
            self.btn_back.clicked.connect(self.on_clicked)

            self.layout.addWidget(self.btn_back)
            self.layout.addStretch(1)
            self.hide()

        def on_clicked(self):
            self.parent.select_ids([])  # deselect all
            self.parent.view.show()
            self.parent.workflow_buttons.show()
            self.hide()

    class DynamicMemberConfigWidget(QWidget):
        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            # from src.members.agent import AgentSettings
            self.stacked_layout = QStackedLayout()

            self.current_member_id = None
            self.agent_config = self.AgentMemberSettings(parent)
            # self.workflow_config = WorkflowConfig()
            # self.human_config = HumanConfig()

            self.stacked_layout.addWidget(self.agent_config)
            # self.stacked_layout.addWidget(self.workflow_config)
            # self.stacked_layout.addWidget(self.human_config)
            # self.stacked_layout.setCurrentWidget(self.agent_config)

            self.setLayout(self.stacked_layout)

        def load(self):
            if self.current_member_id is None:
                return
            if self.current_member_id not in self.parent.members_in_view:
                self.current_member_id = None  # todo
                return
            member = self.parent.members_in_view[self.current_member_id]
            self.display_config_for_member(member)

        def display_config_for_member(self, member):
            # Logic to switch between configurations based on member type
            self.current_member_id = member.id
            member_type = member.member_type
            member_config = member.member_config

            if member_type == "agent":
                self.stacked_layout.setCurrentWidget(self.agent_config)
                self.agent_config.member_id = member.id
                self.agent_config.load_config(member_config)
                self.agent_config.load()
            # elif member_type == "workflow":
            #     self.stacked_layout.setCurrentWidget(self.workflow_config)
            # elif member_type == "human":
            #     self.stacked_layout.setCurrentWidget(self.human_config)

        class AgentMemberSettings(AgentSettings):
            def __init__(self, parent):
                super().__init__(parent)
                self.member_id = None

            def update_config(self):
                self.save_config()

            def save_config(self):
                conf = self.get_config()
                self.parent.members_in_view[self.member_id].member_config = conf
                self.parent.save_config()

    def load_config(self, json_config=None):
        if isinstance(json_config, str):
            json_config = json.loads(json_config)
        if '_TYPE' not in json_config:  # todo maybe change
            json_config = json.dumps({
                '_TYPE': 'workflow',
                'members': [
                    {'id': None, 'agent_id': 0, 'loc_x': 37, 'loc_y': 30, 'config': json_config, 'del': 0}
                ],
                'inputs': [],
            })
        super().load_config(json_config)

    def get_config(self):
        if len(self.members_in_view) == 1:
            member = next(iter(self.members_in_view.values()))
            return member.member_config
        else:
            config = {
                '_TYPE': 'workflow',
                'members': [],
                'inputs': [],
            }
            for member_id, member in self.members_in_view.items():
                config['members'].append({
                    'id': member_id,
                    'agent_id': None,  # member.agent_id,
                    'loc_x': int(member.x()),
                    'loc_y': int(member.y()),
                    'config': member.member_config,  # "{}",  #
                })

            for line_key, line in self.lines.items():
                member_id, input_member_id = line_key

                config['inputs'].append({
                    'member_id': member_id,
                    'input_member_id': input_member_id,
                    'type': line.input_type,
                })

                # # Derive input_members and input_member_types from 'inputs' data
                # for input_member_id, input_type in member.member_inputs.items():
                #     config['inputs'].append({
                #         'member_id': member_id,
                #         'input_member_id': input_member_id,
                #         'type': input_type,
                #     })
            return config  # json.dumps(config)

    @abstractmethod
    def save_config(self):
        pass
        # self.main.page_chat.workflow.load_members()

    def update_member(self, update_list):
        for member_id, attribute, value in update_list:
            member = self.members_in_view.get(member_id)
            if not member:
                return
            setattr(member, attribute, value)
        self.save_config()

    def load(self):
        self.load_members()
        self.load_inputs()

    def load_members(self):
        # Clear any existing members from the scene
        for m_id, member in self.members_in_view.items():
            self.scene.removeItem(member)
        self.members_in_view = {}

        members_data = self.config.get('members', [])

        # Iterate over the parsed 'members' data and add them to the scene
        for member_info in members_data:
            id = member_info['id']
            agent_id = member_info.get('agent_id')
            member_config = member_info.get('config')
            loc_x = member_info.get('loc_x')
            loc_y = member_info.get('loc_y')

            # # Derive input_members and input_member_types from 'inputs' data
            # input_members = [str(inputs_data.get(id, {}).get('input_member_id', 0))]
            # input_member_types = [str(inputs_data.get(id, {}).get('type', ''))]
            #
            # # Join the lists into comma-separated strings
            # member_inp_str = ",".join(input_members)
            # member_type_str = ",".join(input_member_types)

            member = DraggableMember(self, id, loc_x, loc_y, member_config)  # member_inp_str, member_type_str,
            self.scene.addItem(member)
            self.members_in_view[id] = member

        if len(self.members_in_view) == 1:
            # Select the member so that it's config is shown, then hide the workflow panel until more members are added
            self.select_ids([list(self.members_in_view.keys())[0]])
            self.view.hide()
        else:
            # Show the workflow panel in case it was hidden
            self.view.show()

    def load_inputs(self):
        for _, line in self.lines.items():
            self.scene.removeItem(line)
        self.lines = {}

        inputs_data = {input_entry['member_id']: input_entry for input_entry in self.config.get('inputs', [])}
        for member_id, input_entry in inputs_data.items():
            input_member_id = input_entry['input_member_id']
            input_type = input_entry['type']
            start_point = self.members_in_view[input_member_id].output_point
            end_point = self.members_in_view[member_id].input_point
            line = ConnectionLine(input_member_id, member_id, start_point, end_point, input_type)
            self.scene.addItem(line)
            self.lines[(member_id, input_member_id)] = line
    #     for m_id, member in self.members_in_view.items():
    #         for input_member_id, input_type in member.member_inputs.items():
    #             if input_member_id == 0:
    #                 input_member = self.user_bubble
    #             else:
    #                 input_member = self.members_in_view[input_member_id]
    #             key = (m_id, input_member_id)
    #             line = ConnectionLine(key, member.input_point, input_member.output_point, input_type)
    #             self.scene.addItem(line)
    #             self.lines[key] = line

    def select_ids(self, ids):
        for item in self.scene.selectedItems():
            item.setSelected(False)

        for _id in ids:
            self.members_in_view[_id].setSelected(True)

    def on_selection_changed(self):
        selected_agents = [x for x in self.scene.selectedItems() if isinstance(x, DraggableMember)]
        selected_lines = [x for x in self.scene.selectedItems() if isinstance(x, ConnectionLine)]

        is_only_agent = len(self.members_in_view) == 1

        # with block_signals(self.group_topbar): # todo
        if len(selected_agents) == 1:
            member = selected_agents[0]
            self.member_config_widget.display_config_for_member(member)
            self.member_config_widget.show()
            # self.load_agent_settings(selected_agents[0].id)
            if self.compact_mode:
                self.view.hide()
                if not is_only_agent:
                    self.compact_mode_back_button.show()
                # self.compact_mode_back_button.show()
                # self.workflow_buttons.hide()
        else:
            self.member_config_widget.hide()

        # get all member and input configs
        # merge all similar configs like in gamecad
        # dynamic config widget based on object schemas

        # with block_signals(self.group_topbar):  todo
        #     if len(selected_agents) == 1:
        #         self.agent_settings.show()
        #         self.load_agent_settings(selected_agents[0].id)
        #     else:
        #         self.agent_settings.hide()
        #
        #     if len(selected_lines) == 1:
        #         self.group_topbar.input_type_label.show()
        #         self.group_topbar.input_type_combo_box.show()
        #         line = selected_lines[0]
        #         self.group_topbar.input_type_combo_box.setCurrentIndex(line.input_type)
        #     else:
        #         self.group_topbar.input_type_label.hide()
        #         self.group_topbar.input_type_combo_box.hide()

    def add_insertable_entity(self, item):
        self.view.show()
        mouse_scene_point = self.view.mapToScene(self.view.mapFromGlobal(QCursor.pos()))
        item = item.data(Qt.UserRole)
        entity_id = item['id']
        entity_avatar = item['avatar'].split('//##//##//')
        entity_config = json.loads(item['config'])
        self.new_agent = InsertableMember(self, entity_id, entity_avatar, entity_config, mouse_scene_point)
        self.scene.addItem(self.new_agent)
        self.view.setFocus()

    def add_entity(self):
        member_id = max(self.members_in_view.keys()) + 1 if len(self.members_in_view) else 1
        entity_config = self.new_agent.config
        loc_x, loc_y = self.new_agent.x(), self.new_agent.y()
        member = DraggableMember(self, member_id, loc_x, loc_y, entity_config)  # member_inp_str, member_type_str,
        self.scene.addItem(member)
        self.members_in_view[member_id] = member

        self.scene.removeItem(self.new_agent)
        self.new_agent = None

        self.save_config()
        if not self.compact_mode:
            self.parent.load()
        # if hasattr(self.parent, 'top_bar'):
        #     self.parent.top_bar.load()
        # self.parent.parent.load()

    def add_input(self, member_id):
        pass
        # member_id = max(self.members_in_view.keys()) + 1 if len(self.members_in_view) else 1
        # entity_config = self.new_agent.config
        # loc_x, loc_y = self.new_agent.x(), self.new_agent.y()
        # member = DraggableMember(self, member_id, loc_x, loc_y, entity_config)  # member_inp_str, member_type_str,
        # self.scene.addItem(member)
        # self.members_in_view[member_id] = member

        gg = 1
        input_member_id = self.new_line.input_member_id
        # lines = (member_id, inp_member_id): line

        # key = (input_member_id, output_member_id)
        start_point = self.members_in_view[input_member_id].output_point
        end_point = self.members_in_view[member_id].input_point
        line = ConnectionLine(input_member_id, member_id, start_point, end_point, input_type=0)
        self.scene.addItem(line)
        self.lines[(member_id, input_member_id)] = line

        self.scene.removeItem(self.new_line)
        self.new_line = None

        self.save_config()
        if not self.compact_mode:
            self.parent.load()


class WorkflowButtonsWidget(QWidget):
    def __init__(self, parent):  # , extra_tree_buttons=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.layout = CHBoxLayout(self)
        # self.setFixedHeight(10)

        # add 10px margin to the left
        self.layout.addSpacing(15)

        self.btn_add = IconButton(
            parent=self,
            icon_path=':/resources/icon-new.png',
            tooltip='Add',
            size=18,
        )
        self.btn_add.clicked.connect(self.show_context_menu)

        self.btn_save_as = IconButton(
            parent=self,
            icon_path=':/resources/icon-save.png',
            tooltip='Save As',
            size=18,
        )
        self.btn_save_as.clicked.connect(self.save_as)

        self.btn_clear_chat = IconButton(
            parent=self,
            icon_path=':/resources/icon-clear.png',
            tooltip='Clear Chat',
            size=18,
        )
        # self.btn_del = IconButton(
        #     parent=self,
        #     icon_path=':/resources/icon-minus.png',
        #     tooltip='Delete',
        #     size=18,
        # )
        self.layout.addWidget(self.btn_add)
        self.layout.addWidget(self.btn_save_as)
        self.layout.addWidget(self.btn_clear_chat)

        if parent.compact_mode:
            self.btn_save_as.hide()
            self.btn_clear_chat.hide()

        # self.layout.addWidget(self.btn_del)

        # if getattr(parent, 'folder_key', False):
        #     self.btn_new_folder = IconButton(
        #         parent=self,
        #         icon_path=':/resources/icon-new-folder.png',
        #         tooltip='New Folder',
        #         size=18,
        #     )
        #     self.layout.addWidget(self.btn_new_folder)
        #
        # if getattr(parent, 'filterable', False):
        #     self.btn_filter = ToggleButton(
        #         parent=self,
        #         icon_path=':/resources/icon-filter.png',
        #         icon_path_checked=':/resources/icon-filter-filled.png',
        #         tooltip='Filter',
        #         size=18,
        #     )
        #     self.layout.addWidget(self.btn_filter)
        #
        # if getattr(parent, 'searchable', False):
        #     self.btn_search = ToggleButton(
        #         parent=self,
        #         icon_path=':/resources/icon-search.png',
        #         icon_path_checked=':/resources/icon-search-filled.png',
        #         tooltip='Search',
        #         size=18,
        #     )
        #     self.layout.addWidget(self.btn_search)

        self.layout.addStretch(1)

        # self.btn_clear = QPushButton('Clear', self)
        # # self.btn_clear.clicked.connect(self.clear_chat)
        # self.btn_clear.setFixedWidth(75)
        # self.layout.addWidget(self.btn_clear)

    def save_as(self):
        workflow_config = self.parent.get_config()
        text, ok = QInputDialog.getText(self, 'Entity Name', 'Enter a name for the new entity')

        if not ok:
            return False

        try:
            sql.execute("""
                INSERT INTO entities (name, kind, config)
                VALUES (?, ?, ?)
            """, (text, 'AGENT', json.dumps(workflow_config),))

            display_messagebox(
                icon=QMessageBox.Information,
                title='Success',
                text='Entity saved',
            )
        except sqlite3.IntegrityError as e:
            display_messagebox(
                icon=QMessageBox.Warning,
                title='Error',
                text='Name already exists',
            )
            return



    def show_context_menu(self):
        menu = QMenu(self)

        add_agent = menu.addAction('Agent')
        add_user = menu.addAction('User')
        add_tool = menu.addAction('Tool')

        add_agent.triggered.connect(partial(self.choose_member, "AGENT"))
        add_user.triggered.connect(partial(self.choose_member, "USER"))
        add_tool.triggered.connect(partial(self.choose_member, "TOOL"))

        menu.exec_(QCursor.pos())

    def choose_member(self, list_type):
        # if list_type == 'agents':
        #     callback = self.parent.insertAgent
        #     # multiselect = False
        # else:
        #     callback = self.parent.insertTool
        #     # multiselect = True

        # callback with partial of list_type

        list_dialog = ListDialog(
            parent=self,
            title="Add Member",
            list_type=list_type,
            callback=self.parent.add_insertable_entity,
            # multiselect=multiselect
        )
        list_dialog.open()


class CustomGraphicsView(QGraphicsView):
    def __init__(self, scene, parent):
        super(CustomGraphicsView, self).__init__(scene, parent)
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.Antialiasing)
        self.parent = parent

    def mouseMoveEvent(self, event):
        mouse_point = self.mapToScene(event.pos())
        if self.parent.new_line:
            self.parent.new_line.updateEndPoint(mouse_point)
        if self.parent.new_agent:
            self.parent.new_agent.setCentredPos(mouse_point)

        if self.scene():
            self.scene().update()
        self.update()

        super(CustomGraphicsView, self).mouseMoveEvent(event)

    def cancel_new_line(self):
        # Remove the temporary line from the scene and delete it
        self.scene().removeItem(self.parent.new_line)
        self.parent.new_line = None
        self.update()

    def cancel_new_entity(self):
        # Remove the new entity from the scene and delete it
        self.scene().removeItem(self.parent.new_agent)
        self.parent.new_agent = None
        self.update()

    def delete_selected_items(self):
        del_member_ids = set()
        del_inputs = set()
        all_del_objects = []
        all_del_objects_old_brushes = []
        all_del_objects_old_pens = []

        for selected_item in self.parent.scene.selectedItems():
            all_del_objects.append(selected_item)

            if isinstance(selected_item, DraggableMember):
                del_member_ids.add(selected_item.id)

                # Loop through all lines to find the ones connected to the selected agent
                for key, line in self.parent.lines.items():
                    member_id, input_member_id = key
                    if member_id == selected_item.id or input_member_id == selected_item.id:
                        del_inputs.add((member_id, input_member_id))
                        all_del_objects.append(line)

            elif isinstance(selected_item, ConnectionLine):
                del_inputs.add((selected_item.member_id, selected_item.input_member_id))

                # # Loop through all members to find the one connected to the selected line
                # for member_id, member in self.parent.members_in_view.items():
                #     if member_id in (selected_item.member_id, selected_item.input_member_id):
                #         del_member_ids.add(member_id)
                #         all_del_objects.append(member)

        del_count = len(del_member_ids) + len(del_inputs)
        if del_count == 0:
            return

        # fill all objects with a red tint at 30% opacity, overlaying the current item image
        for item in all_del_objects:
            old_brush = item.brush()
            all_del_objects_old_brushes.append(old_brush)
            # modify old brush and add a 30% opacity red fill
            old_pixmap = old_brush.texture()
            new_pixmap = old_pixmap.copy()
            painter = QPainter(new_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)

            painter.fillRect(new_pixmap.rect(),
                             QColor(255, 0, 0, 126))
            painter.end()
            new_brush = QBrush(new_pixmap)
            item.setBrush(new_brush)

            old_pen = item.pen()
            all_del_objects_old_pens.append(old_pen)
            new_pen = QPen(QColor(255, 0, 0, 255),
                           old_pen.width())
            item.setPen(new_pen)

        self.parent.scene.update()

        # ask for confirmation
        retval = display_messagebox(
            icon=QMessageBox.Warning,
            text="Are you sure you want to delete the selected items?",
            title="Delete Items",
            buttons=QMessageBox.Ok | QMessageBox.Cancel,
        )
        if retval == QMessageBox.Ok:
            for obj in all_del_objects:
                self.parent.scene.removeItem(obj)

            for member_id in del_member_ids:
                self.parent.members_in_view.pop(member_id)
            for line_key in del_inputs:
                self.parent.lines.pop(line_key)

            self.parent.save_config()
            if not self.parent.compact_mode:
                self.parent.parent.load()
        else:
            for item in all_del_objects:
                item.setBrush(all_del_objects_old_brushes.pop(0))
                item.setPen(all_del_objects_old_pens.pop(0))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:  # todo - refactor
            if self.parent.new_line:
                self.cancel_new_line()
            if self.parent.new_agent:
                self.cancel_new_entity()

        elif event.key() == Qt.Key_Delete:
            if self.parent.new_line:
                self.cancel_new_line()
                return
            if self.parent.new_agent:
                self.cancel_new_entity()
                return

            self.delete_selected_items()
        else:
            super(CustomGraphicsView, self).keyPressEvent(event)

    def mousePressEvent(self, event):
        # todo
        if self.parent.new_agent:
            self.parent.add_entity()
        else:
            mouse_scene_position = self.mapToScene(event.pos())
            for member_id, member in self.parent.members_in_view.items():
                if isinstance(member, DraggableMember):
                    if self.parent.new_line:
                        input_point_pos = member.input_point.scenePos()
                        # if within 20px
                        if (mouse_scene_position - input_point_pos).manhattanLength() <= 20:
                            self.parent.add_input(member_id)  # self.input_member_id, member_id)
                            return
                            # self.parent.new_line.attach_to_member(agent.id)
                            # # agent.close_btn.hide()
                    else:
                        output_point_pos = member.output_point.scenePos()
                        output_point_pos.setX(output_point_pos.x() + 8)
                        # if within 20px
                        if (mouse_scene_position - output_point_pos).manhattanLength() <= 20:
                            self.parent.new_line = TemporaryConnectionLine(self.parent, member)
                            self.parent.scene.addItem(self.parent.new_line)
                            return

            # check user bubble
            output_point_pos = self.parent.user_bubble.output_point.scenePos()
            output_point_pos.setX(output_point_pos.x() + 8)
            # if within 20px
            if (mouse_scene_position - output_point_pos).manhattanLength() <= 20:
                if self.parent.new_line:
                    self.parent.scene.removeItem(self.parent.new_line)

                self.parent.new_line = TemporaryConnectionLine(self.parent, self.parent.user_bubble)
                self.parent.scene.addItem(self.parent.new_line)
                return
            if self.parent.new_line:
                # Remove the temporary line from the scene and delete it
                self.scene().removeItem(self.parent.new_line)
                self.parent.new_line = None

        super(CustomGraphicsView, self).mousePressEvent(event)


class FixedUserBubble(QGraphicsEllipseItem):
    def __init__(self, parent):
        super(FixedUserBubble, self).__init__(0, 0, 50, 50)
        from src.gui.style import TEXT_COLOR
        self.id = 0
        self.parent = parent

        self.setPos(-42, 75)

        # set border color
        self.setPen(QPen(QColor(TEXT_COLOR), 1))

        pixmap = colorize_pixmap(QPixmap(":/resources/icon-user.png"))
        self.setBrush(QBrush(pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

        self.output_point = ConnectionPoint(self, False)
        self.output_point.setPos(self.rect().width() - 4, self.rect().height() / 2)

        self.setAcceptHoverEvents(True)

    def hoverMoveEvent(self, event):
        # Check if the mouse is within 20 pixels of the output point
        if self.output_point.contains(event.pos() - self.output_point.pos()):
            self.output_point.setHighlighted(True)
        else:
            self.output_point.setHighlighted(False)
        super(FixedUserBubble, self).hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.output_point.setHighlighted(False)
        super(FixedUserBubble, self).hoverLeaveEvent(event)


class InsertableMember(QGraphicsEllipseItem):
    def __init__(self, parent, agent_id, icon, config, pos):
        super(InsertableMember, self).__init__(0, 0, 50, 50)
        from src.gui.style import TEXT_COLOR
        self.parent = parent
        self.id = agent_id
        self.config = config
        member_type = config.get('_TYPE', 'agent')
        def_avatar = None
        pen = None

        if member_type == 'workflow':
            pass
        elif member_type == 'user':
            def_avatar = ':/resources/icon-user.png'
            pen = QPen(QColor(TEXT_COLOR), 1)
        else:
            pen = QPen(QColor(TEXT_COLOR), 1)

        if pen:
            # set border color
            self.setPen(pen)
        if isinstance(icon, QPixmap):
            pixmap = icon
        else:
            pixmap = path_to_pixmap(icon, diameter=50, def_avatar=def_avatar)
        self.setBrush(QBrush(pixmap.scaled(50, 50)))
        self.setCentredPos(pos)

    def setCentredPos(self, pos):
        self.setPos(pos.x() - self.rect().width() / 2, pos.y() - self.rect().height() / 2)


class DraggableMember(QGraphicsEllipseItem):
    def __init__(self, parent, member_id, loc_x, loc_y, member_config):
        super(DraggableMember, self).__init__(0, 0, 50, 50)
        from src.gui.style import TEXT_COLOR

        self.parent = parent
        self.id = member_id
        self.member_type = member_config.get('_TYPE', 'agent')
        self.member_config = member_config

        # member_type = member_config.get('_TYPE', 'agent')
        if self.member_type == 'workflow':
            pass
        else:
            # set border color
            self.setPen(QPen(QColor(TEXT_COLOR), 1))

        # if member_type_str:
        #     member_inp_str = '0' if member_inp_str == 'NULL' else member_inp_str  # todo dirty
        # self.member_inputs = dict(
        #     zip([int(x) for x in member_inp_str.split(',')],
        #         member_type_str.split(','))) if member_type_str else {}

        self.setPos(loc_x, loc_y)

        # agent_config = json.loads(agent_config)
        # member_type = member_config.get('_TYPE', 'agent')
        if self.member_type == 'agent':
            avatars = member_config.get('info.avatar_path', '')
        elif self.member_type == 'workflow':
            avatars = [member['config'].get('info.avatar_path', '') for member in member_config.get('members', [])]
        else:
            avatars = ''
        hide_responses = member_config.get('group.hide_responses', False)
        opacity = 0.2 if hide_responses else 1
        diameter = 50
        if self.member_type == 'user':
            def_avatar = ':/resources/icon-user.png'
        else:
            def_avatar = None
        pixmap = path_to_pixmap(avatars, opacity=opacity, diameter=diameter, def_avatar=def_avatar)

        self.setBrush(QBrush(pixmap.scaled(diameter, diameter)))

        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)

        self.input_point = ConnectionPoint(self, True)
        self.output_point = ConnectionPoint(self, False)
        self.input_point.setPos(0, self.rect().height() / 2)
        self.output_point.setPos(self.rect().width() - 4, self.rect().height() / 2)

        self.setAcceptHoverEvents(True)

        # Create the highlight background item
        self.highlight_background = self.HighlightBackground(self)
        self.highlight_background.setPos(self.rect().width()/2, self.rect().height()/2)
        self.highlight_background.hide()  # Initially hidden

        # self.highlight_states = {
        #     'responding': '#0bde2b',
        #     'waiting': '#f7f7f7',
        # }

    def toggle_highlight(self, enable, color=None):
        """Toggles the visual highlight on or off."""
        if enable:
            self.highlight_background.use_color = color
            self.highlight_background.show()
        else:
            self.highlight_background.hide()

    def mouseReleaseEvent(self, event):
        super(DraggableMember, self).mouseReleaseEvent(event)
        new_loc_x = self.x()
        new_loc_y = self.y()
        self.parent.update_member([
            (self.id, 'loc_x', new_loc_x),
            (self.id, 'loc_y', new_loc_y)
        ])

    def mouseMoveEvent(self, event):
        if self.output_point.contains(event.pos() - self.output_point.pos()):
            return

        if self.parent.new_line:
            return

        # if mouse not inside scene, return
        cursor = event.scenePos()
        if not self.parent.view.rect().contains(cursor.toPoint()):
            return

        super(DraggableMember, self).mouseMoveEvent(event)
        for line in self.parent.lines.values():
            line.updatePosition()

    def hoverMoveEvent(self, event):
        # Check if the mouse is within 20 pixels of the output point
        if self.output_point.contains(event.pos() - self.output_point.pos()):
            self.output_point.setHighlighted(True)
        else:
            self.output_point.setHighlighted(False)
        super(DraggableMember, self).hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.output_point.setHighlighted(False)
        super(DraggableMember, self).hoverLeaveEvent(event)

    class HighlightBackground(QGraphicsItem):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.outer_diameter = 100  # Diameter including the gradient
            self.inner_diameter = 50  # Diameter of the hole, same as the DraggableMember's ellipse
            self.use_color = None  # Uses text color when none

        def boundingRect(self):
            return QRectF(-self.outer_diameter / 2, -self.outer_diameter / 2, self.outer_diameter, self.outer_diameter)

        def paint(self, painter, option, widget=None):
            from src.gui.style import TEXT_COLOR
            gradient = QRadialGradient(QPointF(0, 0), self.outer_diameter / 2)
            # text_color_ = QColor(TEXT_COLOR)
            color = self.use_color or QColor(TEXT_COLOR)

            gradient.setColorAt(0, color)  # Inner color of gradient
            gradient.setColorAt(1, QColor(255, 255, 0, 0))  # Outer color of gradient

            # Create a path for the outer ellipse (gradient)
            outer_path = QPainterPath()
            outer_path.addEllipse(-self.outer_diameter / 2, -self.outer_diameter / 2, self.outer_diameter,
                                  self.outer_diameter)

            # Create a path for the inner hole
            inner_path = QPainterPath()
            inner_path.addEllipse(-self.inner_diameter / 2, -self.inner_diameter / 2, self.inner_diameter,
                                  self.inner_diameter)

            # Subtract the inner hole from the outer path
            final_path = QPainterPath(outer_path)
            final_path = final_path.subtracted(inner_path)

            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)  # No border
            painter.drawPath(final_path)


class TemporaryConnectionLine(QGraphicsPathItem):
    def __init__(self, parent, agent):
        super(TemporaryConnectionLine, self).__init__()
        from src.gui.style import TEXT_COLOR
        self.parent = parent
        self.input_member_id = agent.id
        self.output_point = agent.output_point
        self.setPen(QPen(QColor(TEXT_COLOR), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.temp_end_point = self.output_point.scenePos()
        self.updatePath()

    def updatePath(self):
        output_pos = self.output_point.scenePos()
        end_pos = self.temp_end_point
        x_distance = (end_pos - output_pos).x()  # Assuming horizontal distance matters
        y_distance = abs((end_pos - output_pos).y())  # Assuming horizontal distance matters

        # Set control points offsets to be a fraction of the horizontal distance
        fraction = 0.61  # Adjust the fraction as needed (e.g., 0.2 for 20%)
        offset = x_distance * fraction
        if offset < 0:
            offset *= 3
            offset = min(offset, -40)
        else:
            offset = max(offset, 40)
            offset = min(offset, y_distance)
        offset = abs(offset)  # max(abs(offset), 10)

        path = QPainterPath(output_pos)
        ctrl_point1 = output_pos + QPointF(offset, 0)
        ctrl_point2 = end_pos - QPointF(offset, 0)
        path.cubicTo(ctrl_point1, ctrl_point2, end_pos)
        self.setPath(path)

    def updateEndPoint(self, end_point):
        self.temp_end_point = end_point
        self.updatePath()

    def attach_to_member(self, member_id):
        self.parent.add_input(self.input_member_id, member_id)


class ConnectionLine(QGraphicsPathItem):
    def __init__(self, input_member_id, member_id, start_point, end_point, input_type=0):  # key, start_point, end_point=None, input_type=0):
        super(ConnectionLine, self).__init__()
        from src.gui.style import TEXT_COLOR
        self.member_id, self.input_member_id = (member_id, input_member_id)
        self.start_point = start_point
        self.end_point = end_point
        self.input_type = int(input_type)

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.color = QColor(TEXT_COLOR)

        self.updatePath()

        self.setPen(QPen(self.color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setZValue(-1)

    def paint(self, painter, option, widget):
        line_width = 4 if self.isSelected() else 2
        current_pen = self.pen()
        current_pen.setWidth(line_width)
        # set to a dashed line if input type is 1
        if self.input_type == 1:
            current_pen.setStyle(Qt.DashLine)
        painter.setPen(current_pen)
        painter.drawPath(self.path())

    def updateEndPoint(self, end_point):
        self.end_point = end_point
        self.updatePath()

    def updatePosition(self):
        self.updatePath()
        self.scene().update(self.scene().sceneRect())

    def updatePath(self):
        start_point = self.start_point.scenePos()
        end_point = self.end_point.scenePos()
        x_distance = (end_point - start_point).x()
        y_distance = abs((end_point - start_point).y())

        # Set control points offsets to be a fraction of the horizontal distance
        fraction = 0.61  # Adjust the fraction as needed (e.g., 0.2 for 20%)
        offset = x_distance * fraction
        if offset < 0:
            offset *= 3
            offset = min(offset, -40)
        else:
            offset = max(offset, 40)
            offset = min(offset, y_distance)
        offset = abs(offset)  # max(abs(offset), 10)

        path = QPainterPath(start_point)
        ctrl_point1 = start_point + QPointF(offset, 0)
        ctrl_point2 = end_point - QPointF(offset, 0)
        path.cubicTo(ctrl_point1, ctrl_point2, end_point)
        self.setPath(path)
    # def updatePath(self):
    #     path = QPainterPath(self.start_point.scenePos())
    #     ctrl_point1 = self.start_point.scenePos() + QPointF(50, 0)
    #     ctrl_point2 = self.end_point.scenePos() - QPointF(50, 0)
    #     path.cubicTo(ctrl_point1, ctrl_point2, self.end_point.scenePos())
    #     self.setPath(path)


class ConnectionPoint(QGraphicsEllipseItem):
    def __init__(self, parent, is_input):
        radius = 2
        super(ConnectionPoint, self).__init__(0, 0, 2 * radius, 2 * radius, parent)
        self.is_input = is_input
        self.setBrush(QBrush(Qt.darkGray if is_input else Qt.darkRed))
        self.connections = []

    def setHighlighted(self, highlighted):
        if highlighted:
            self.setBrush(QBrush(Qt.red))
        else:
            self.setBrush(QBrush(Qt.black))

    def contains(self, point):
        distance = (point - self.rect().center()).manhattanLength()
        return distance <= 12


# class TemporaryConnectionLine(QGraphicsPathItem):
#     def __init__(self, parent, agent):
#         super(TemporaryConnectionLine, self).__init__()
#         self.parent = parent
#         self.input_member_id = agent.id
#         self.output_point = agent.output_point
#         self.setPen(QPen(QColor(TEXT_COLOR), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
#         self.temp_end_point = self.output_point.scenePos()
#         self.updatePath()
#
#     def updatePath(self):
#         path = QPainterPath(self.output_point.scenePos())
#         ctrl_point1 = self.output_point.scenePos() + QPointF(50, 0)
#         ctrl_point2 = self.temp_end_point - QPointF(50, 0)
#         path.cubicTo(ctrl_point1, ctrl_point2, self.temp_end_point)
#         self.setPath(path)
#
#     def updateEndPoint(self, end_point):
#         self.temp_end_point = end_point
#         self.updatePath()
#
#     def attach_to_member(self, member_id):
#         self.parent.add_input(self.input_member_id, member_id)
