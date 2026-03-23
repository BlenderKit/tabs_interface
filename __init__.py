bl_info = {
    "name": "Tabs interface",
    "author": "Vilem Duha",
    "version": (3, 0),
    "blender": (4, 5, 0),
    "location": "Everywhere(almost)",
    "description": "Blender tabbed.",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "All",
}

import bpy
import copy  # for deepcopy dicts
import inspect
import math
import os
import re
from bpy.app.handlers import persistent

from . import panel_order

DEBUG = False

_update_tabs = []
# _update_pdata = []
_update_categories = []
_extra_activations = []
USE_DEFAULT_POLL = False  # Pie menu editor compatibility

IGNORE_SPACES = ("TOPBAR", "INFO", "PREFERENCES")
IGNORE_REGIONS = ("HEADER", "NAVIGATION_BAR", "TOOLS", "TOOL_HEADER")


@classmethod
def noPoll(cls, context):
    return False


@classmethod
def yesPoll(cls, context):
    return True


@classmethod
def smartPoll(cls, context):
    prefs = bpy.context.preferences.addons[__package__].preferences
    try:
        polled = cls.opoll(context)
    except Exception:
        return False  # original poll crashed — panel doesn't belong in this context

    if USE_DEFAULT_POLL:
        return polled

    if context.region.type == "TOOL_HEADER":
        return polled
    item = bpy.context.window_manager.panelData.get(cls.realID)
    if prefs.enable_disabling:
        if prefs.disable_PROPERTIES and context.area.type == "PROPERTIES":
            return polled
        if prefs.disable_UI and context.region.type == "UI":
            return polled
    if item is None:
        return False

    if hasattr(cls, "bl_parent_id"):
        parent = getattr(bpy.types, cls.bl_parent_id)
        polled = parent.poll(context) and polled

    return (
        ((item.activated and item.activated_category) or item.pin)
        and polled
        and item.show
        and (prefs.original_panels)
    )


def drawHeaderPin(cls, context):
    layout = cls.layout

    if (
        hasattr(bpy.context.window_manager, "panelData")
        and bpy.context.window_manager.panelData.get(cls.realID) is not None
        and context.region.type != "TOOL_HEADER"
    ):
        pd = bpy.context.window_manager.panelData[cls.realID]
        if pd.pin:
            icon = "PINNED"
        else:
            icon = "UNPINNED"
        layout.prop(
            bpy.context.window_manager.panelData[cls.realID],
            "pin",
            icon_only=True,
            icon=icon,
            emboss=False,
        )

    if hasattr(cls, "orig_draw_header"):
        cls.orig_draw_header(context)


def format_header_text(text):
    # Replace underscores with spaces and capitalize each word
    return " ".join(word.capitalize() for word in text.replace("_", " ").split())


def introspect_draw_header(draw_header_method):
    """
    Inspects the draw_header method of a Blender panel and extracts the text used within it.

    Args:
    draw_header_method (function): The draw_header method of a Blender panel to be introspected.

    Returns:
    str: The extracted text from the draw_header method. It returns an empty string if no text is found.
    """

    # Retrieve the source code of the draw_header method
    source_code = inspect.getsource(draw_header_method)
    # Regex pattern to find instances of text='something' or text="something" inside parentheses
    pattern = re.compile(r'\([^)]*?text=["\'](.*?)["\'][^)]*?\)')
    matches = pattern.findall(source_code)

    # Loop through matches to find the first non-empty match
    match = ""
    for m in matches:
        if m != "":
            match = m
            break

    # If no match found, look for property names used in layout.prop calls with an empty text attribute
    if match == "":
        pattern_prop = re.compile(
            r'\.prop\([^,]+,\s*["\'](.*?)["\']\s*,\s*text=["\']["\']\)'
        )
        matches_prop = pattern_prop.findall(source_code)
        for m in matches_prop:
            if m != "":
                match = format_header_text(m)
                break

    # Return the found text, or an empty string if none is found
    return match


def processPanelForTabs(panel):
    # processed panels have a realID attribute
    if not hasattr(panel, "realID"):

        panel.realID = panel.bl_rna.identifier

        # process panel category
        panel.had_category = False
        if hasattr(panel, "bl_category"):
            panel.had_category = True
            if not hasattr(panel, "orig_category"):
                panel.orig_category = panel.bl_category
            panel.bl_category = "Tools"
        # elif panel.bl_space_type == 'VIEW_3D' and panel.bl_region_type == 'TOOLS':
        #     panel.bl_category = 'Tools'
        #     panel.orig_category = 'Misc'
        else:
            # use tools for all panels without category
            panel.bl_category = "Tools"
            panel.orig_category = "Tools"

        # process and rewrite panel poll
        if not hasattr(panel, "opoll"):
            if not hasattr(panel, "poll"):
                panel.poll = yesPoll
            panel.opoll = panel.poll
            panel.poll = smartPoll

        # backup and rewrite original draw header function
        if hasattr(panel, "draw_header"):
            if panel.bl_label == "":
                h_text = introspect_draw_header(panel.draw_header)
                if h_text != "":
                    panel.orig_bl_label = panel.bl_label
                    panel.bl_label = h_text

            panel.orig_draw_header = panel.draw_header
        panel.draw_header = drawHeaderPin

        # goodby original panel!
        bpy.utils.unregister_class(panel)

        if hasattr(panel, "bl_options"):
            if "DEFAULT_CLOSED" in panel.bl_options:
                panel.bl_options.remove("DEFAULT_CLOSED")
        try:
            bpy.utils.register_class(panel)
        except Exception as e:
            print(e)


def fixOriginalPanel(tp_name):
    """brings panel to state before tabs"""

    tp = getattr(bpy.types, tp_name)
    bpy.utils.unregister_class(tp)
    if hasattr(tp, "opoll"):
        tp.poll = tp.opoll
        del tp.opoll
    if hasattr(tp, "orig_draw_header"):
        print(tp.bl_label)
        tp.draw_header = tp.orig_draw_header
        del tp.orig_draw_header
    else:
        if hasattr(
            tp, "draw_header"
        ):  # unprocessed panels might still have no draw_header
            del tp.draw_header
    if hasattr(tp, "orig_category"):
        tp.bl_category = tp.orig_category
        if not tp.had_category:
            del tp.bl_category

        del tp.orig_category
    if hasattr(tp, "realID"):
        del tp.realID
    bpy.utils.register_class(tp)


DEFAULT_PANEL_PROPS = [
    "__class__",
    "__contains__",
    "__delattr__",
    "__delitem__",
    "__dict__",
    "__dir__",
    "__doc__",
    "__eq__",
    "__format__",
    "__ge__",
    "__getattribute__",
    "__getitem__",
    "__gt__",
    "__hash__",
    "__init__",
    "__le__",
    "__lt__",
    "__module__",
    "__ne__",
    "__new__",
    "__reduce__",
    "__reduce_ex__",
    "__repr__",
    "__setattr__",
    "__setitem__",
    "__sizeof__",
    "__slots__",
    "__str__",
    "__subclasshook__",
    "__weakref__",
    "_dyn_ui_initialize",
    "append",
    "as_pointer",
    "bl_category",
    "bl_context",
    "bl_description",
    "bl_idname",
    "bl_label",
    "bl_options",
    "bl_region_type",
    "bl_rna",
    "bl_space_type",
    "COMPAT_ENGINES",
    "draw",
    "draw_header",
    "driver_add",
    "driver_remove",
    "get",
    "id_data",
    "is_property_hidden",
    "is_property_readonly",
    "is_property_set",
    "items",
    "keyframe_delete",
    "keyframe_insert",
    "keys",
    "orig_category",
    "path_from_id",
    "path_resolve",
    "poll",
    "opoll",
    "prepend",
    "property_unset",
    "remove",
    "type_recast",
    "values",
]

NOCOPY_PANEL_PROPS = [
    "__class__",
    "__contains__",
    "__delattr__",
    "__delitem__",
    "__dict__",
    "__dir__",
    "__doc__",
    "__eq__",
    "__format__",
    "__ge__",
    "__getattribute__",
    "__getitem__",
    "__gt__",
    "__hash__",
    "__init__",
    "__le__",
    "__lt__",
    "__module__",
    "__ne__",
    "__new__",
    "__reduce__",
    "__reduce_ex__",
    "__repr__",
    "__setattr__",
    "__setitem__",
    "__sizeof__",
    "__slots__",
    "__str__",
    "__subclasshook__",
    "__weakref__",
    "_dyn_ui_initialize",
    "append",
    "as_pointer",
    "bl_category",
    "bl_context",
    "bl_description",
    "bl_idname",
    "bl_label",
    "bl_options",
    "bl_region_type",
    "bl_rna",
    "bl_space_type",
    "COMPAT_ENGINES",
    "driver_add",
    "driver_remove",
    "get",
    "id_data",
    "is_property_hidden",
    "is_property_readonly",
    "is_property_set",
    "items",
    "keyframe_delete",
    "keyframe_insert",
    "keys",
    "orig_category",
    "path_from_id",
    "path_resolve",
    "poll",
    "prepend",
    "property_unset",
    "remove",
    "type_recast",
    "values",
]


class tabSetups(bpy.types.PropertyGroup):
    """stores data for tabs"""

    tabsenum: bpy.props.EnumProperty(
        name="Post processor", items=[("tabID", "tabb", "tabbiiiieeee")]
    )
    show: bpy.props.BoolProperty(name="show", default=True)  # , update = updatePin)
    active_tab: bpy.props.StringProperty(name="Active tab", default="Machine")
    active_category: bpy.props.StringProperty(name="Active category", default="None")


class tabCategoryData(bpy.types.PropertyGroup):
    # ''stores data for categories''
    show: bpy.props.BoolProperty(name="show", default=True)


class panelData(bpy.types.PropertyGroup):
    """stores data for panels"""

    pin: bpy.props.BoolProperty(name="pin", default=False)  # , update = updatePin)
    show: bpy.props.BoolProperty(name="show", default=True)
    activated: bpy.props.BoolProperty(name="activated", default=False)
    activated_category: bpy.props.BoolProperty(name="activated category", default=True)
    category: bpy.props.StringProperty(name="category", default="Tools")
    parent: bpy.props.StringProperty(name="parent", default="")
    space: bpy.props.StringProperty(name="space", default="")
    region: bpy.props.StringProperty(name="region", default="")
    context: bpy.props.StringProperty(name="context", default="")


def getlabel(panel):
    return panel.bl_label


DONT_USE = [
    "DATA_PT_modifiers",
    "OBJECT_PT_constraints",
    "BONE_PT_constraints",
    "__dir__",
]


def getPanelIDs():
    """rebuilds panel ID's dictionary"""
    s = bpy.types.WindowManager
    if not hasattr(s, "panelIDs"):
        s.panelIDs = {}

    newIDs = []
    panel_tp = bpy.types.Panel
    typedir = dir(bpy.types)
    btypeslen = len(typedir)

    for tp_name in typedir:
        if (
            tp_name.find("_tabs") == -1 and tp_name not in DONT_USE
        ):  # and tp_name.find('NODE_PT_category_')==-1
            tp = getattr(bpy.types, tp_name)
            if (
                tp == panel_tp
                or not inspect.isclass(tp)
                or not issubclass(tp, panel_tp)
                or tp.bl_space_type == "PREFERENCES"
                or hasattr(tp, "bl_region_type")
                and tp.bl_region_type == "HEADER"
                or hasattr(tp, "bl_options")
                and "INSTANCED" in tp.bl_options
            ):
                continue

            if s.panelIDs.get(tp.bl_rna.identifier) is None:
                newIDs.append(tp)
            s.panelIDs[tp.bl_rna.identifier] = tp
            if tp.is_registered != True:
                print("not registered", tp.bl_label)

    return newIDs


def buildTabDir(panels):
    """rebuilds tab directory"""
    if DEBUG:
        print("rebuild tabs ", len(panels))
    # disabled reading from scene,
    if hasattr(bpy.types.WindowManager, "panelSpaces"):
        spaces = bpy.types.WindowManager.panelSpaces
    else:
        spaces = copy.deepcopy(panel_order.spaces)
        for sname in spaces:
            if sname not in IGNORE_SPACES:
                space = spaces[sname]

                for rname in space:
                    if rname not in IGNORE_REGIONS and not (
                        rname == "WINDOW" and sname == "VIEW_3D"
                    ):
                        nregion = []
                        region = space[rname]

                        for p in region:
                            if type(p) == str:
                                panel = getattr(bpy.types, p, None)
                                if panel:
                                    if p in DONT_USE or (
                                        hasattr(panel, "bl_options")
                                        and "INSTANCED" in panel.bl_options
                                    ):
                                        continue
                                    processPanelForTabs(panel)
                                    nregion.append(panel)
                                else:
                                    if DEBUG:
                                        print("non existing panel " + str(p))
                                    # nregion.append(panel)
                        space[rname] = nregion

    for panel in panels:

        if hasattr(panel, "bl_space_type"):
            st = panel.bl_space_type
            if st not in IGNORE_SPACES:
                if spaces.get(st) is None:
                    spaces[st] = {}

                if hasattr(panel, "bl_region_type"):

                    rt = panel.bl_region_type
                    if rt not in IGNORE_REGIONS and not (
                        rt == "WINDOW" and st == "VIEW_3D"
                    ):
                        if spaces[st].get(rt) is None:
                            spaces[st][rt] = []

                        processPanelForTabs(panel)
                        if panel not in spaces[st][rt]:
                            spaces[st][rt].append(panel)
    for sname in spaces:
        space = spaces[sname]
        for rname in space:
            region = space[rname]
            for p in region:
                if not p.is_registered:
                    region.remove(p)
    return spaces


def updatePanels():
    newIDs = getPanelIDs()  # bpy.types.WindowManager.panels =
    bpy.types.WindowManager.panelSpaces = buildTabDir(newIDs)
    createSceneTabData()


def getPanels(getspace, getregion):
    if not hasattr(bpy.types.WindowManager, "panelIDs"):
        updatePanels()
    panels = bpy.types.WindowManager.panelSpaces[getspace][getregion]
    return panels


def drawEnable(self, context):
    layout = self.layout
    row = layout.row()
    row.label(text="Enable:")


def layoutActive(self, context):
    layout = self.layout
    layout.active = True
    layout.enabled = True


class CarryLayout:
    def __init__(self, layout):
        self.layout = layout


def drawNone(self, context):
    pass


def tabRow(layout):
    prefs = bpy.context.preferences.addons[__package__].preferences
    row = layout.row(align=prefs.fixed_width)  # not prefs.fixed_width)
    if not prefs.fixed_width:
        row.scale_y = prefs.scale_y
    if not prefs.fixed_width:
        row.alignment = "LEFT"
    return row


def nextSplit(regwidth=100, width=None, ratio=None, last=0):  # 6 11 27
    if width is not None:
        restw = regwidth - (regwidth * last)
        if width > 0:
            neww = regwidth * last + width
            nextsplit = width / restw

        else:
            neww = regwidth - width
            nextsplit = 1 - (-width / regwidth) / (1 - last)
            # print(-width/regwidth, 1-last, nextsplit)
        newtotalsplit = neww / regwidth
    if ratio is not None:
        if last < ratio:
            nextsplit = (ratio - last) / (1 - last)
            newtotalsplit = ratio
        else:
            nextsplit = 0
            newtotalsplit = last
            # print('wrong split')
    return nextsplit, newtotalsplit


def getApproximateFontStringWidth(st):
    import blf
    ui_scale = bpy.context.preferences.view.ui_scale * bpy.context.preferences.system.pixel_size  #blender pixel size
    font_id = 0  # default Blender UI font
    blf.size(font_id, round(15 * ui_scale))
    width, _ = blf.dimensions(font_id, st)
    return width + round(20 * ui_scale)  # add button padding (both sides)


def drawTabsLayout(
    self,
    context,
    layout,
    tabpanel=None,
    operator_name="wm.activate_panel",
    texts=[],
    ids=[],
    tdata=[],
    active="",
    enable_hiding=False,
):  # tdata=[],
    """Creates and draws actual layout of tabs"""

    # Fetch preferences and calculate initial layout dimensions
    ui_scale = context.preferences.view.ui_scale
    prefs = bpy.context.preferences.addons[__package__].preferences
    w = context.region.width  # width of the region
    margin = int(18 * ui_scale)
    if prefs.box:
        margin += int(10 * ui_scale)
    iconwidth = int(20 * ui_scale)
    oplist = []

    # Optional box layout
    if prefs.box:
        layout = layout.box()
    layout = layout.column(align=True)

    # Initialize variables for dynamic width calculation

    if not prefs.fixed_width:  # DYNAMIC layout
        baserest = w - margin
        restspace = baserest

        # Variables for tab width and alignment
        tw = 0
        splitalign = True
        row = tabRow(layout)
        split = row

        rows = 0
        i = 0
        lastsplit = None

        # Iterate through each tab
        for t, id in zip(texts, ids):
            # Calculate tab width and adjust layout accordingly
            if prefs.emboss and restspace != baserest:
                drawtext = "| " + t
            else:
                drawtext = t
            tw = getApproximateFontStringWidth(drawtext)
            if enable_hiding and prefs.hiding:
                tw += iconwidth
            if i == 0 and tabpanel is not None and prefs.enable_folding:
                tw += iconwidth
                split.prop(
                    tabpanel, "show", icon_only=True, icon="DOWNARROW_HLT", emboss=False
                )

            if enable_hiding and not prefs.hiding and not tdata[i].show:
                tw = 0

            oldrestspace = restspace
            restspace = restspace - tw

            if restspace > 0:

                split = split.split(factor=tw / oldrestspace, align=splitalign)

            else:
                drawtext = t
                tw = getApproximateFontStringWidth(drawtext)
                if (
                    rows == 0 and enable_hiding and prefs.show_hiding_icon
                ):  # draw hiding mode icon here
                    if prefs.hiding:
                        tw += iconwidth
                rows += 1
                oldrestspace = baserest
                restspace = baserest - tw
                row = tabRow(layout)
                split = row.split(factor=tw / oldrestspace, align=splitalign)

            if enable_hiding and prefs.hiding:
                split.prop(tdata[i], "show", text=drawtext)
                oplist.append(None)
            else:
                if not enable_hiding or tdata[i].show:

                    if active[i]:
                        op = split.operator(
                            operator_name, text=drawtext, emboss=prefs.emboss
                        )
                    else:
                        op = split.operator(
                            operator_name, text=drawtext, emboss=not prefs.emboss
                        )
                    oplist.append(op)
                else:
                    oplist.append(None)

            i += 1
            if rows == 0 and enable_hiding:
                lastsplit = split
                firstrow = row
                lastsplit_restspace = restspace
        if lastsplit is not None:
            # split = lastsplit
            # if lastsplit_restspace-iconwidth>0:
            # split = lastsplit.split( factor = (lastsplit_restspace - iconwidth)/lastsplit_restspace, align = False)
            # split = split.split()
            if prefs.show_hiding_icon:
                if prefs.hiding:
                    icon = "HIDE_ON"
                else:
                    icon = "HIDE_OFF"
                firstrow.prop(
                    prefs, "hiding", icon_only=True, icon=icon, emboss=not prefs.emboss
                )

    else:  # Fixed width (grid) layout
        # Calculate tab width and number of columns
        w = w - margin
        wtabcount = math.floor(w / 80)
        if wtabcount == 0:
            wtabcount = 1

        if prefs.fixed_columns:

            space = context.area.type

            if space == "PROPERTIES":
                wtabcount = prefs.columns_properties

                # print(self.bl_context)
                if (
                    self.bl_context == "modifier"
                    or self.bl_context == "constraint"
                    or self.bl_context == "bone_constraint"
                ):
                    wtabcount = prefs.columns_modifiers
            else:
                wtabcount = prefs.columns_rest
        ti = 0
        rows = 0
        row = tabRow(layout)

        lastsplit = 0
        # hiding
        i = 0

        # Loop through each tab and construct the grid layout
        for t, id in zip(texts, ids):
            if tabpanel is not None and i == 0 and prefs.enable_folding:
                ratio, lastsplit = nextSplit(regwidth=w, width=iconwidth, last=0)
                split = row.split(factor=ratio, align=True)

                split.prop(
                    tabpanel, "show", icon_only=True, icon="DOWNARROW_HLT", emboss=False
                )
                row = split.split(align=True)

            if (enable_hiding and prefs.hiding) or (not enable_hiding or tdata[i].show):
                # nextSplit( regwidth = 100,width = none, percent = None, lasttotalsplit = 0)

                splitratio = (ti + 1) / (wtabcount)
                if splitratio == 1 and rows == 0 and enable_hiding:
                    ratio, lastsplit = nextSplit(
                        regwidth=w, width=-iconwidth, last=lastsplit
                    )
                else:
                    ratio, lastsplit = nextSplit(
                        regwidth=w, ratio=splitratio, last=lastsplit
                    )
                # split = row

                if ratio == 1:
                    split = row
                else:
                    split = row.split(factor=ratio, align=True)

                drawn = False

                if enable_hiding and prefs.hiding:
                    split.prop(tdata[i], "show", text=t)
                    drawn = True
                else:
                    if not enable_hiding or tdata[i].show:

                        if active[i]:
                            op = split.operator(
                                operator_name, text=t, icon="NONE", emboss=prefs.emboss
                            )
                        else:
                            op = split.operator(
                                operator_name,
                                text=t,
                                icon="NONE",
                                emboss=not prefs.emboss,
                            )
                        oplist.append(op)
                        drawn = True
                if ratio != 1:
                    row = split.split(align=True)
                ti += 1
            else:
                oplist.append(None)
            i += 1
            if ti == wtabcount or i == len(texts):

                if enable_hiding and rows == 0:
                    if (
                        ti != wtabcount
                    ):  # this doesn't work, it's single tab eye drawing. not sure why!!!
                        # print('last eye')
                        ratio, lastsplit = nextSplit(
                            regwidth=w, width=-iconwidth, last=lastsplit
                        )
                        # print(ratio, lastsplit)
                        split = row.split(factor=ratio, align=True)
                        row = split.split(align=True)
                    if prefs.show_hiding_icon:
                        if prefs.hiding:
                            icon = "HIDE_ON"
                        else:
                            icon = "HIDE_OFF"
                        row.prop(
                            prefs,
                            "hiding",
                            icon_only=True,
                            icon=icon,
                            emboss=not prefs.emboss,
                        )
                ti = 0
                rows += 1
                lastsplit = 0
                row = tabRow(layout)

        if ti != 0:
            while ti < wtabcount:
                row.label(text="")
                ti += 1
    return oplist


def drawUpDown(self, context, tabID):
    layout = self.layout
    s = bpy.context.window_manager
    # r = bpy.context.region
    tabpanel_data = s.panelTabData.get(tabID)
    active_tab = tabpanel_data.active_tab
    op = layout.operator("wm.panel_up", text="up 50", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 50
    op = layout.operator("wm.panel_up", text="up 10", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 10
    op = layout.operator("wm.panel_up", text="up", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 1
    op = layout.operator("wm.panel_down", text="down", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 1
    op = layout.operator("wm.panel_down", text="down 10", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 10
    op = layout.operator("wm.panel_down", text="down 50", emboss=True)
    op.panel_id = active_tab
    op.tabpanel_id = tabID
    op.step = 50


def mySeparator(layout):
    prefs = bpy.context.preferences.addons[__package__].preferences

    if not prefs.box:
        layout.separator()
        layout.separator()
    if prefs.emboss and not prefs.box:
        b = layout.box()
        b.scale_y = 0


def drawFoldHeader(self, context, tabpanel_data):
    layout = self.layout
    row = layout.row()
    if tabpanel_data.show:
        icon = "DOWNARROW_HLT"
    else:
        icon = "RIGHTARROW"
    row.prop(tabpanel_data, "show", icon_only=True, icon=icon, emboss=False)
    row.label(text=self.bl_label)


def drawTabs(self, context, plist, tabID):
    space = context.space_data.type
    prefs = bpy.context.preferences.addons[__package__].preferences
    s = bpy.context.window_manager
    # r = bpy.context.region
    if not hasattr(s, "panelTabData"):
        return []
    tabpanel_data = s.panelTabData.get(tabID)
    panel_data = s.panelData
    if tabpanel_data is None:
        _update_tabs.append(self)
        return []

    if prefs.reorder_panels:
        drawUpDown(self, context, tabID)
    emboss = prefs.emboss

    # print('au')
    draw_panels = []
    draw_panels_levels = [[], [], [], [], []]
    categories = {}
    categories_list = []  # this because it can be sorted, not like dict.

    active_tab = tabpanel_data.active_tab  #
    active_category = tabpanel_data.active_category
    hasactivetab = False
    hasactivecategory = False

    if not tabpanel_data.show:
        drawFoldHeader(self, context, tabpanel_data)

    top_panel = None
    stale = []
    for p in plist:
        if not hasattr(p, "realID") or panel_data.get(p.realID) is None:
            stale.append(p)
            continue
        if hasattr(p, "bl_options"):
            if "HIDE_HEADER" in p.bl_options:
                top_panel = p
                plist.remove(p)
                draw_panels.append(p)  # draw unconditionally, before tab content
    for p in stale:
        plist.remove(p)

    for p in plist:
        if hasattr(
            p, "bl_category"
        ):  # and not (p.bl_region_type == 'UI' and p.bl_space_type == 'VIEW_3D'):#additional checks for Archimesh only!
            if categories.get(p.orig_category) is None:
                categories[p.orig_category] = [p]
                categories_list.append(p.orig_category)
            else:
                categories[p.orig_category].append(p)
        if tabpanel_data.active_tab == p.realID:
            hasactivetab = True

    for p in plist:
        pdata = panel_data[p.realID]
        if p not in draw_panels and pdata.pin:
            ppanel = p
            level = 0
            while hasattr(ppanel, "bl_parent_id"):
                level += 1
                ppanel = getattr(bpy.types, ppanel.bl_parent_id)

            draw_panels_levels[level].append(p)
            continue

        if pdata.activated and (
            len(categories) == 1 or p.orig_category == active_category
        ):
            add_panel = True
            # go through parents to check activation status
            ppanel = p

            level = 0
            while add_panel and hasattr(ppanel, "bl_parent_id"):
                level += 1
                ppanel = getattr(bpy.types, ppanel.bl_parent_id)
                if not hasattr(ppanel, "realID") or panel_data.get(ppanel.realID) is None:
                    add_panel = False
                    break
                add_panel = add_panel and panel_data[ppanel.realID].activated

            if add_panel:
                draw_panels_levels[level].append(p)

    for level in draw_panels_levels:
        draw_panels.extend(level)

    if len(categories) > 0:
        # print('hascategories')
        catorder = panel_order.categories

        sorted_categories = []
        cdata = []
        categories_ok = True
        for c in categories:
            if s.categories.get(c) is None:
                _update_tabs.append(self)
                print("categories problem ", categories)
                categories_ok = False
        if not categories_ok:
            return []

        for c1 in catorder:
            for c in categories:
                if c == c1:
                    sorted_categories.append(c)

                    cdata.append(s.categories[c])
        for c in categories:
            if c not in sorted_categories:
                sorted_categories.append(c)
                cdata.append(s.categories[c])
        for c in categories:
            if c == active_category:
                hasactivecategory = True

        if not hasactivecategory:
            active_category = sorted_categories[0]
        active = []
        for cname in sorted_categories:
            if cname == active_category:
                active.append(True)
            else:
                active.append(False)

    if top_panel is not None:
        top_panel.draw(self, context)

    preview = None

    layout = self.layout
    maincol = layout.column(align=True)

    # draw panel categories first
    if len(categories) > 1:  # EVIL TOOL PANELS!
        # row=tabRow(maincol)
        if len(categories) > 1:
            if tabpanel_data.show:
                catops = drawTabsLayout(
                    self,
                    context,
                    maincol,
                    tabpanel=tabpanel_data,
                    operator_name="wm.activate_category",
                    texts=sorted_categories,
                    ids=sorted_categories,
                    tdata=cdata,
                    active=active,
                    enable_hiding=True,
                )
                for cat, cname in zip(catops, sorted_categories):
                    if cat is not None:
                        cplist = categories[cname]
                        cat.category = cname
                        cat.tabpanel_id = tabID
                        # print('catlen ',cname , len(cplist), cplist)
                        if len(cplist) == 1:
                            cat.single_panel = cplist[0].realID

        plist = categories[active_category]
        if len(plist) > 1:
            mySeparator(maincol)

        category_active_tab = tabpanel_data.get("active_tab_" + active_category)
        if category_active_tab is not None:
            active_tab = category_active_tab
            hasactivetab = True

    # draw panels tabs
    if len(plist) > 1:  # property windows
        # Draw panels here.
        # these are levels of subpanels(2.8 madness)
        texts = [[], [], [], []]
        ids = [[], [], [], []]
        tdata = [[], [], [], []]
        tabpanels = [[], [], [], []]
        active = [[], [], [], []]

        maxlevel = 0
        for p in plist:

            if p.bl_label == "Preview":
                preview = p
            else:
                visible = True

                level = 0
                ppanel = p
                while visible and hasattr(ppanel, "bl_parent_id"):
                    level += 1
                    ppanel = getattr(bpy.types, ppanel.bl_parent_id)
                    if not hasattr(ppanel, "realID") or panel_data.get(ppanel.realID) is None:
                        visible = False
                        break
                    visible = visible and panel_data[ppanel.realID].activated

                maxlevel = max(maxlevel, level)
                if visible:
                    texts[level].append(p.bl_label)
                    ids[level].append(p.realID)
                    tabpanels[level].append(p)
                    tdata[level].append(panel_data[p.realID])
                    active[level].append(panel_data[p.realID].activated)
        if tabpanel_data.show:
            if len(categories) == 1:
                tabpanel = tabpanel_data
            else:
                tabpanel = None
            for level in range(0, maxlevel + 1):
                tabops = drawTabsLayout(
                    self,
                    context,
                    maincol,
                    tabpanel=tabpanel,
                    operator_name="wm.activate_panel",
                    texts=texts[level],
                    ids=ids[level],
                    tdata=tdata[level],
                    active=active[level],
                    enable_hiding=False,
                )
                for op, p in zip(tabops, tabpanels[level]):
                    if op is not None:
                        op.panel_id = p.realID
                        op.tabpanel_id = tabID
                        op.category = active_category

                if level < maxlevel:
                    mySeparator(maincol)

    if len(draw_panels) == 0 and len(plist) > 0:
        p = plist[0]
        if p not in draw_panels:
            draw_panels.append(p)
            _extra_activations.append(p)

    layout.active = True

    if preview is not None:
        preview.draw(self, context)
    return draw_panels


def _resolve_active_names(items, active_names):
    """Return active_names if any are still present in items, else fall back to the first item."""
    if any(name in items for name in active_names):
        return active_names
    return [items[0].name]


def _draw_item_tabs(self, context, maincol, items, active_names, operator_name, name_attr):
    """Draw a tab row for items and assign name_attr on each returned operator."""
    names = items.keys()
    active = [item.name in active_names for item in items]
    tabops = drawTabsLayout(
        self, context, maincol,
        operator_name=operator_name,
        texts=names, ids=names, active=active,
    )
    for op, name in zip(tabops, names):
        setattr(op, name_attr, name)


def modifiersDraw(self, context):
    prefs = bpy.context.preferences.addons[__package__].preferences
    ob = context.object
    layout = self.layout
    layout.operator_menu_enum("object.modifier_add", "type")
    if len(ob.modifiers) > 0:
        if not prefs.enable_disabling or not (
            prefs.enable_disabling and prefs.disable_MODIFIERS
        ):
            maincol = layout.column(align=True)

            for am in list(ob.active_modifiers):
                if am not in ob.modifiers:
                    ob.active_modifiers.remove(am)
            active_modifiers = _resolve_active_names(ob.modifiers, ob.active_modifiers)

            if len(ob.modifiers) > 1:
                _draw_item_tabs(self, context, maincol, ob.modifiers, active_modifiers,
                                "object.activate_modifier", "modifier_name")
                mySeparator(maincol)
            layout.template_modifiers()
        else:
            layout.template_modifiers()


def constraintsDraw(self, context):
    prefs = bpy.context.preferences.addons[__package__].preferences
    ob = context.object
    layout = self.layout
    if ob.type == "ARMATURE" and ob.mode == "POSE":
        box = layout.box()
        box.alert = True
        box.label(icon="INFO", text="Constraints for active bone do not live here")
        box.operator(
            "wm.properties_context_change",
            icon="CONSTRAINT_BONE",
            text="Go to Bone Constraints tab...",
        ).context = "BONE_CONSTRAINT"
    else:
        layout.operator_menu_enum(
            "object.constraint_add", "type", text="Add Object Constraint"
        )
    if len(ob.constraints) > 0:
        if not prefs.enable_disabling or not (
            prefs.enable_disabling and prefs.disable_MODIFIERS
        ):
            maincol = layout.column(align=True)
            active_constraints = _resolve_active_names(ob.constraints, ob.active_constraints)
            if len(ob.constraints) > 1:
                _draw_item_tabs(self, context, maincol, ob.constraints, active_constraints,
                                "object.activate_constraint", "constraint_name")
            layout.template_constraints(use_bone_constraints=False)
        else:
            layout.template_constraints(use_bone_constraints=False)


def boneConstraintsDraw(self, context):
    prefs = bpy.context.preferences.addons[__package__].preferences
    pb = context.pose_bone
    layout = self.layout
    layout.operator_menu_enum("pose.constraint_add", "type", text="Add Bone Constraint")
    if len(pb.constraints) > 0:
        if not prefs.enable_disabling or not (
            prefs.enable_disabling and prefs.disable_MODIFIERS
        ):
            maincol = layout.column(align=True)
            active_constraints = _resolve_active_names(pb.constraints, pb.active_constraints)
            if len(pb.constraints) > 1:
                _draw_item_tabs(self, context, maincol, pb.constraints, active_constraints,
                                "object.activate_posebone_constraint", "constraint_name")
            layout.template_constraints(use_bone_constraints=True)
        else:
            layout.template_constraints(use_bone_constraints=True)


def drawPanels(self, context, draw_panels):
    layout = self.layout

    for drawPanel in draw_panels:
        if drawPanel.bl_label != "":
            box = layout.box()
            box.scale_y = 1

            row = box.row()
            row.scale_y = 0.8
            if hasattr(drawPanel, "orig_draw_header"):
                fakeself = CarryLayout(row)

                drawPanel.orig_draw_header(fakeself, context)

            if not hasattr(drawPanel, "orig_bl_label"):
                row.label(text=drawPanel.bl_label)

            pd = bpy.context.window_manager.panelData[drawPanel.realID]
            if pd.pin:
                icon = "PINNED"
            else:
                icon = "UNPINNED"
            row.prop(
                bpy.context.window_manager.panelData[drawPanel.realID],
                "pin",
                icon_only=True,
                icon=icon,
                emboss=False,
            )
        # these are various functions defined all around blender for panels. We need them to draw the panel inside the tab panel

        if hasattr(drawPanel, "draw"):
            try:
                pInstance = drawPanel(bpy.context.window_manager)
                pInstance.layout = layout
                drawPanel.draw(pInstance, context)
            except Exception as e:
                panel_id = getattr(drawPanel, "bl_idname", repr(drawPanel))
                print(f"tabs_interface: skipping panel {panel_id!r}: {e}")
        layoutActive(self, context)

        layout.separator()
        b = layout.box()
        b.scale_y = 0


def pollTabs(panels, context):
    draw_plist = []
    for p in panels:
        polled = True
        if hasattr(p, "poll"):
            try:
                if hasattr(p, "opoll"):
                    polled = p.opoll(context)
            except Exception:
                pass

        if polled:
            draw_plist.append(p)
    return draw_plist


def getFilteredTabs(self, context):
    getspace = context.area.type
    getregion = context.region.type
    tab_panel_category = ""
    if hasattr(self, "bl_category"):
        tab_panel_category = self.bl_category
    panellist = getPanels(getspace, getregion)
    tabpanel = self

    possible_tabs = []
    possible_tabs_wider = []
    categories = []
    for panel in panellist:
        if not hasattr(panel, "bl_label"):
            print("not a panel", panel)

        else:
            polled = True
            if not panel.is_registered:  # somehow it can happen between updates
                polled = False
            if hasattr(panel, "bl_context"):
                pctx = panel.bl_context.upper()
                if panel.bl_context == "particle":  # property particle panels
                    pctx = "PARTICLES"

                if hasattr(context.space_data, "context"):
                    if not pctx == context.space_data.context:
                        polled = False

                elif hasattr(context, "mode"):
                    # TOOLS NEED DIFFERENT APPROACH!!! THS IS JUST AN UGLY UGLY HACK....
                    if panel.bl_context == "mesh_edit":
                        pctx = "EDIT_MESH"
                    elif panel.bl_context == "curve_edit":
                        pctx = "EDIT_CURVE"
                    elif panel.bl_context == "surface_edit":
                        pctx = "EDIT_SURFACE"
                    elif panel.bl_context == "text_edit":
                        pctx = "EDIT_TEXT"
                    elif panel.bl_context == "armature_edit":
                        pctx = "EDIT_ARMATURE"
                    elif panel.bl_context == "mball_edit":
                        pctx = "EDIT_METABALL"
                    elif panel.bl_context == "lattice_edit":
                        pctx = "EDIT_LATTICE"
                    elif panel.bl_context == "posemode":
                        pctx = "POSE"
                    elif panel.bl_context == "mesh_edit":
                        pctx = "SCULPT"
                    elif panel.bl_context == "weightpaint":
                        pctx = "PAINT_WEIGHT"
                    elif panel.bl_context == "vertexpaint":
                        pctx = "PAINT_VERTEX"
                    elif panel.bl_context == "imagepaint":
                        pctx = "PAINT_TEXTURE"
                    elif panel.bl_context == "objectmode":
                        pctx = "OBJECT"
                    if panel.bl_context == "particlemode":  # Tools particle panels
                        pctx = "PARTICLE"

                    if not pctx == context.mode:
                        polled = False

                    if panel.bl_context == "scene":  # openGL lights addon problem
                        polled = True
                # print((context.space_data.context))
            if polled:
                possible_tabs_wider.append(panel)
            if hasattr(panel, "bl_category"):
                if panel.bl_category != tab_panel_category:
                    polled = False
            # print(polled)
            if polled:
                possible_tabs.append(panel)
    # print('possible', len(possible_tabs))
    draw_tabs_list = pollTabs(possible_tabs, context)
    self.tabcount = len(draw_tabs_list)
    return draw_tabs_list


def drawRegionUI(self, context):  # , getspace, getregion, tabID):
    prefs = bpy.context.preferences.addons[__package__].preferences
    # print(dir(self))

    tabID = self.bl_idname

    draw_tabs_list = getFilteredTabs(self, context)
    # print('pre',self.tabcount)
    # print('filtered',len(draw_tabs_list))
    draw_panels = drawTabs(self, context, draw_tabs_list, tabID)
    if not prefs.original_panels:
        # print(draw_panels)
        drawPanels(self, context, draw_panels)


class PanelUp(bpy.types.Operator):
    """panel order utility"""

    bl_idname = "wm.panel_up"
    bl_label = "panel up"
    bl_options = {"REGISTER"}

    tabpanel_id: bpy.props.StringProperty(
        name="tab panel name",
        default="you didnt assign panel to the operator in ui def",
    )
    panel_id: bpy.props.StringProperty(name="panel name", default="")
    step: bpy.props.IntProperty(name="step", default=1)

    def execute(self, context):
        # unhide_panel(self.tabpanel_id)
        tabpanel = getattr(bpy.types, self.tabpanel_id, None)
        panel_id = self.panel_id

        ps = bpy.types.WindowManager.panelSpaces

        # print('up1')
        for step in range(0, self.step):
            for s in ps:
                space = ps[s]

                for r in space:

                    # print('up2')
                    region = space[r]
                    swapped = False
                    for i, p in enumerate(region):
                        if p.realID == panel_id and i > 0:
                            for i1 in range(i - 1, 0, -1):
                                p1 = region[i1]
                                family = False
                                if (
                                    hasattr(p, "bl_context")
                                    and hasattr(p1, "bl_context")
                                    and p.bl_context == p1.bl_context
                                ):
                                    family = True
                                if (
                                    hasattr(p, "orig_category")
                                    and hasattr(p1, "orig_category")
                                    and p.orig_category == p1.orig_category
                                ):
                                    family = True
                                # print(family, p.bl_context)
                                if family:
                                    swapped = True
                                    region[i] = p1
                                    region[i1] = p

                                    break
                            if not swapped:
                                region[i] = region[i - 1]
                                region[i - 1] = p

        return {"FINISHED"}


class PanelDown(bpy.types.Operator):
    """panel order utility"""

    bl_idname = "wm.panel_down"
    bl_label = "panel down"
    bl_options = {"REGISTER"}

    tabpanel_id: bpy.props.StringProperty(
        name="tab panel name",
        default=" you didnt assign panel to the operator in ui def",
    )
    panel_id: bpy.props.StringProperty(name="panel name", default="")
    step: bpy.props.IntProperty(name="step", default=1)

    def execute(self, context):
        # unhide_panel(self.tabpanel_id)
        tabpanel = getattr(bpy.types, self.tabpanel_id, None)
        panel_id = self.panel_id

        ps = bpy.types.WindowManager.panelSpaces

        for step in range(0, self.step):
            swapped = False

            for s in ps:
                space = ps[s]
                if swapped:
                    break
                for r in space:
                    if swapped:
                        break
                    region = space[r]
                    for i, p in enumerate(region):
                        if p.realID == panel_id and i < len(region) - 1:
                            #
                            for i1 in range(i + 1, len(region)):
                                p1 = region[i1]
                                family = False
                                if (
                                    hasattr(p, "bl_context")
                                    and hasattr(p1, "bl_context")
                                    and p.bl_context == p1.bl_context
                                ):
                                    family = True
                                if (
                                    hasattr(p, "orig_category")
                                    and hasattr(p1, "orig_category")
                                    and p.orig_category == p1.orig_category
                                ):
                                    family = True
                                # print(family, p.bl_context)
                                if family:
                                    swapped = True
                                    region[i] = p1
                                    region[i1] = p

                                    break

                            if not swapped:
                                region[i] = region[i + 1]
                                region[i + 1] = p

                            if swapped:
                                break

        return {"FINISHED"}


class WritePanelOrder(bpy.types.Operator):
    """write panel order utility"""

    bl_idname = "wm.write_panel_order"
    bl_label = "write panel order"
    bl_options = {"REGISTER"}

    def execute(self, context):
        state_before = {}  # copy.deepcopy(panel_order.spaces)
        ps = bpy.types.WindowManager.panelSpaces
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        panel_order_path = os.path.join(addon_dir, "panel_order.py")
        f = open(panel_order_path, "w")
        nps = {}
        for s in ps:
            if s not in IGNORE_SPACES:
                space = ps[s]
                nps[s] = {}
                for r in space:
                    if r not in IGNORE_REGIONS and not (
                        r == "WINDOW" and s == "VIEW_3D"
                    ):

                        nps[s][r] = []
                        nregion = nps[s][r]
                        region = space[r]

                        for p in region:
                            # nregion.append('bpy.types.'+p.realID)
                            nregion.append(p.realID)
                        # nregion.sort()
                        # space[r] = nregion
        # try to append panels that were not open(addons e.t.c.) so we can save sorting for ALL addons :)
        # print(state_before)
        lastp = ""
        for s in state_before:

            space = state_before[s]
            if s not in IGNORE_SPACES:
                for r in space:
                    # ignore horizontal regions:
                    if r not in IGNORE_REGIONS and not (
                        r == "WINDOW" and s == "VIEW_3D"
                    ):
                        region = space[r]
                        for p in region:
                            if p not in nps[s][r]:
                                if nps[s][r].count(lastp) > 0:
                                    idx = nps[s][r].index(lastp)
                                    nps[s][r].insert(idx + 1, p)
                                    # print('insert', p)
                                    # print(region)
                                else:
                                    # print('write',p)
                                    nps[s][r].append(p)
                                    # print('append', p)
                                    # print(region)
                            lastp = p

        ddef = str(nps)
        ddef = ddef.replace("},", "},\n    ")
        ddef = ddef.replace("],", "],\n    ")
        ddef = ddef.replace("[", "[\n    ")
        ddef = ddef.replace(", ", ",\n    ")
        ddef = ddef.replace("]},", "]},\n    ")
        ddef = ddef.replace("]}}", "]}}")

        categories_str = str(panel_order.categories)
        file_content = f"categories = {categories_str}\n\nspaces = {ddef}\n"
        f.write(file_content)
        f.close()
        return {"FINISHED"}


class ActivatePanel(bpy.types.Operator):
    """activate panel"""

    bl_idname = "wm.activate_panel"
    bl_label = "activate panel"
    bl_options = {"REGISTER"}

    tabpanel_id: bpy.props.StringProperty(
        name="tab panel name", default="PROPERTIES_PT_tabs"
    )
    panel_id: bpy.props.StringProperty(name="panel name", default="")
    category: bpy.props.StringProperty(name="panel name", default="")
    shift: bpy.props.BoolProperty(name="shift", default=False)

    def execute(self, context):
        prefs = bpy.context.preferences.addons[__package__].preferences
        tabpanel = getattr(bpy.types, self.tabpanel_id, None)
        s = bpy.context.window_manager
        s.panelTabData[self.tabpanel_id].active_tab = self.panel_id

        panel = tabpanel
        item = s.panelData.get(self.panel_id)
        apanel = getattr(bpy.types, self.panel_id)
        # print(context.area.type, context.region.type)
        plist = s.panelSpaces[panel.bl_space_type][panel.bl_region_type]

        if not self.shift:
            for p in plist:
                c1 = hasattr(apanel, "bl_context")
                c2 = hasattr(p, "bl_context")
                if c1 and c2:
                    context_same = p.bl_context == apanel.bl_context
                else:
                    context_same = True

                parent1 = hasattr(apanel, "bl_parent_id")
                parent2 = hasattr(p, "bl_parent_id")
                if parent1 and parent2:
                    parents_same = p.bl_parent_id == apanel.bl_parent_id
                elif parent1 or parent2:
                    parents_same = False
                else:
                    parents_same = True

                if (
                    p.bl_region_type == panel.bl_region_type
                    and p.bl_space_type == panel.bl_space_type
                    and context_same
                    and (p.orig_category == apanel.orig_category)
                    and parents_same
                ):
                    # this condition does : check region, space
                    #                        same context - mainly property window
                    #                       same category - mainly toolbar. This makes it possible to have active tabs inside categories and not having them all display panels. magic!
                    pdata = s.panelData[p.realID]
                    pdata.activated = False

        # if prefs.original_panels:
        if self.shift and item.activated:
            item.activated = False
        else:
            item.activated = True
            # this is also allready obsolete? not yet so much?
            # if self.category!= '':
            #    s.panelTabData[self.tabpanel_id]['active_tab_'+self.category] = self.panel_id
        # reactivate the category, this is when category wasn't initialized so active category is first category.

        s.panelTabData[self.tabpanel_id].active_category = self.category

        tab_update_handler(bpy.context.scene)
        return {"FINISHED"}

    def invoke(self, context, event):
        if event.shift:  # for Multi-selection self.obj = context.selected_objects
            self.shift = True
            # print('shift')
        else:
            self.shift = False
        return self.execute(context)


class ActivateCategory(bpy.types.Operator):
    """activate category"""

    bl_idname = "wm.activate_category"
    bl_label = "activate panel category"
    bl_options = {"REGISTER"}

    tabpanel_id: bpy.props.StringProperty(
        name="tab panel name", default="PROPERTIES_PT_tabs"
    )
    category: bpy.props.StringProperty(name="category", default="ahoj")
    single_panel: bpy.props.StringProperty(name="category", default="")
    shift: bpy.props.BoolProperty(name="shift", default=False)

    def execute(self, context):
        prefs = bpy.context.preferences.addons[__package__].preferences
        # unhide_panel(self.tabpanel_id)
        tabpanel = getattr(bpy.types, self.tabpanel_id)
        s = bpy.context.window_manager
        s.panelTabData[self.tabpanel_id].active_category = self.category

        return {"FINISHED"}

    def invoke(self, context, event):
        prefs = bpy.context.preferences.addons[__package__].preferences
        if event.shift:  # for Multi-selection self.obj = context.selected_objects
            self.shift = True
            # print('shift')
        else:
            self.shift = False
        if self.single_panel != "":
            bpy.ops.wm.activate_panel(
                tabpanel_id=self.tabpanel_id,
                panel_id=self.single_panel,
                category=self.category,
                shift=self.shift,
            )

        s = bpy.context.window_manager
        tabpanel = getattr(bpy.types, self.tabpanel_id)
        plist = s.panelSpaces[tabpanel.bl_space_type][tabpanel.bl_region_type]

        # if not self.shift:
        for p in plist:
            pdata = s.panelData[p.realID]
            if p.orig_category == self.category:
                pdata.activated_category = True
            else:
                pdata.activated_category = False
        return self.execute(context)


class ActivateModifier(bpy.types.Operator):
    """activate modifier"""

    bl_idname = "object.activate_modifier"
    bl_label = "activate modifier"
    bl_options = {"REGISTER"}

    modifier_name: bpy.props.StringProperty(name="Modifier name", default="")
    shift: bpy.props.BoolProperty(name="shift", default=False)

    def execute(self, context):
        ob = bpy.context.active_object
        if not self.shift:
            ob.active_modifiers.clear()

        if self.shift and self.modifier_name in ob.active_modifiers:
            ob.active_modifiers.remove(self.modifier_name)
        elif self.modifier_name not in ob.active_modifiers:
            ob.active_modifiers.append(self.modifier_name)

        active = ob.active_modifiers if ob.active_modifiers else (
            [ob.modifiers[0].name] if ob.modifiers else []
        )
        for md in ob.modifiers:
            md.show_expanded = md.name in active
        return {"FINISHED"}

    def invoke(self, context, event):
        if event.shift:  # for Multi-selection self.obj = context.selected_objects
            self.shift = True
            # print('shift')
        else:
            self.shift = False
        return self.execute(context)


class ActivateConstraint(bpy.types.Operator):
    """activate constraint"""

    bl_idname = "object.activate_constraint"
    bl_label = "activate constraint"
    bl_options = {"REGISTER"}

    constraint_name: bpy.props.StringProperty(name="Constraint name", default="")
    shift: bpy.props.BoolProperty(name="shift", default=False)

    def execute(self, context):
        ob = bpy.context.active_object
        if not self.shift:
            ob.active_constraints.clear()

        if self.shift and self.constraint_name in ob.active_constraints:
            ob.active_constraints.remove(self.constraint_name)
        elif self.constraint_name not in ob.active_constraints:
            ob.active_constraints.append(self.constraint_name)

        active = ob.active_constraints if ob.active_constraints else (
            [ob.constraints[0].name] if ob.constraints else []
        )
        for con in ob.constraints:
            con.show_expanded = con.name in active
        return {"FINISHED"}

    def invoke(self, context, event):
        if event.shift:  # for Multi-selection self.obj = context.selected_objects
            self.shift = True
            # print('shift')
        else:
            self.shift = False
        return self.execute(context)


class ActivatePoseBoneConstraint(bpy.types.Operator):
    """activate constraint"""

    bl_idname = "object.activate_posebone_constraint"
    bl_label = "activate constraint"
    bl_options = {"REGISTER"}

    constraint_name: bpy.props.StringProperty(name="Constraint name", default="")
    shift: bpy.props.BoolProperty(name="shift", default=False)

    def execute(self, context):
        pb = bpy.context.pose_bone
        if not self.shift:
            pb.active_constraints.clear()

        if self.shift and self.constraint_name in pb.active_constraints:
            pb.active_constraints.remove(self.constraint_name)
        elif self.constraint_name not in pb.active_constraints:
            pb.active_constraints.append(self.constraint_name)

        active = pb.active_constraints if pb.active_constraints else (
            [pb.constraints[0].name] if pb.constraints else []
        )
        for con in pb.constraints:
            con.show_expanded = con.name in active
        return {"FINISHED"}

    def invoke(self, context, event):
        if event.shift:  # for Multi-selection self.obj = context.selected_objects
            self.shift = True
            # print('shift')
        else:
            self.shift = False
        return self.execute(context)


class TabsPanel:
    @classmethod
    def poll(cls, context):
        prefs = bpy.context.preferences.addons[__package__].preferences
        if prefs is None:
            return True
        if prefs.enable_disabling:
            if prefs.disable_PROPERTIES and context.area.type == "PROPERTIES":
                return False
            if prefs.disable_UI and context.region.type == "UI":
                return False
        return True  # tabspanel_info==None or len(draw_tabs_list) >1


# THIS FUNCTION DEFINES ALL THE TABS PANELS.!!!
def createPanels():
    spaces = bpy.types.WindowManager.panelSpaces
    s = bpy.types.WindowManager
    definitions = []
    panelIDs = []
    pdef = "class %s(TabsPanel,bpy.types.Panel):\n    bl_space_type = '%s'\n    bl_region_type = '%s'\n    bl_options = {'HIDE_HEADER'}\n    %s\n    bl_label = 'Tabs'\n    bl_idname = '%s'\n    draw = drawRegionUI\n"
    for sname in spaces:
        space = spaces[sname]
        for rname in space:
            region = space[rname]

            categories = {}
            contexts = {}
            for panel in region:
                if (
                    hasattr(panel, "bl_context") and panel.bl_context != "scene"
                ):  # scene context because of opengl lights addon
                    contexts[panel.bl_context] = 1
                if hasattr(panel, "bl_category"):
                    categories[panel.bl_category] = True

            # categories['nothing'] = True#nonsense to debug condition now.

            if len(categories) > 0:
                # for cname in categories:
                # if panel.bl_space_type == 'VIEW_3D' and panel.bl_region_type == 'TOOLS':
                #   cname = 'Tools'
                # else:
                #    cname = 'Default'
                cname = "Tools"  # tools
                cnamefixed = cname.upper()
                cnamefixed = cnamefixed.replace(" ", "_")
                cnamefixed = cnamefixed.replace("/", "_")
                pname = "%s_PT_%s_%s_tabs" % (
                    sname.upper(),
                    rname.upper(),
                    cnamefixed.upper(),
                )

                cstring = pdef % (
                    pname,
                    sname.upper(),
                    rname.upper(),
                    "bl_category = '%s'" % cname,
                    pname,
                )

                definitions.append(cstring)
                panelIDs.append(pname)
            elif len(contexts) > 0:
                for cname in contexts:
                    cnamefixed = cname.upper()
                    cnamefixed = cnamefixed.replace(" ", "_")
                    cnamefixed = cnamefixed.replace("/", "_")
                    pname = "%s_PT_%s_%s_tabs" % (
                        sname.upper(),
                        rname.upper(),
                        cnamefixed.upper(),
                    )

                    cstring = pdef % (
                        pname,
                        sname.upper(),
                        rname.upper(),
                        "bl_context = '%s'" % cname,
                        pname,
                    )

                    definitions.append(cstring)
                    panelIDs.append(pname)
            else:
                pname = "%s_PT_%s_tabs" % (sname.upper(), rname.upper())
                cstring = pdef % (pname, sname.upper(), rname.upper(), "", pname)
                definitions.append(cstring)
                panelIDs.append(pname)

    return definitions, panelIDs


class VIEW3D_PT_transform(bpy.types.Panel):
    bl_label = "Transform"
    bl_idname = "VIEW3D_PT_transform"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        pass


class VIEW3D_PT_Transform(bpy.types.Panel):
    bl_label = "Transform"
    bl_idname = "VIEW3D_PT_Transform"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    @classmethod
    def poll(cls, context):
        return bpy.context.active_object is not None

    def draw(self, context):
        layout = self.layout

        ob = context.object
        layout.alignment = "RIGHT"
        row = layout.row()

        row.column(align=True).prop(ob, "location")
        # align=False);
        row.column(align=True).prop(ob, "lock_location")
        row = layout.row()
        if ob.rotation_mode == "QUATERNION":
            row.column().prop(ob, "rotation_quaternion", text="Rotation")

        elif ob.rotation_mode == "AXIS_ANGLE":
            # row.column().label(text="Rotation")
            # row.column().prop(pchan, "rotation_angle", text="Angle")
            # row.column().prop(pchan, "rotation_axis", text="Axis")
            row.column().prop(ob, "rotation_axis_angle", text="Rotation")

        else:
            row.column().prop(ob, "rotation_euler", text="Rotation")
        row.column(align=True).prop(ob, "lock_rotation")
        layout.prop(ob, "rotation_mode", text="")
        row = layout.row()
        row.column().prop(ob, "scale")
        row.column(align=True).prop(ob, "lock_scale")
        row = layout.row()
        row.column(align=True).prop(ob, "dimensions")


class TabInterfacePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    # here you define the addons customizable props
    original_panels: bpy.props.BoolProperty(
        name="Default blender panels", description="", default=False
    )
    fixed_width: bpy.props.BoolProperty(name="Grid layout", default=True)
    fixed_columns: bpy.props.BoolProperty(name="Fixed number of colums", default=True)
    columns_properties: bpy.props.IntProperty(
        name="Columns in property window", default=3, min=1
    )
    columns_modifiers: bpy.props.IntProperty(
        name="Columns in modifiers and constraints", default=3, min=1
    )
    columns_rest: bpy.props.IntProperty(name="Columns in side panels", default=2, min=1)
    emboss: bpy.props.BoolProperty(name="Invert tabs drawing", default=True)
    # align_rows : bpy.props.BoolProperty(name = 'Align tabs in rows', default=True)
    box: bpy.props.BoolProperty(name="Draw box around tabs", default=True)
    scale_y: bpy.props.FloatProperty(name="vertical scale of tabs", default=1)
    reorder_panels: bpy.props.BoolProperty(
        name="allow reordering panels (developer tool only)", default=False
    )
    hiding: bpy.props.BoolProperty(
        name="Enable panel hiding",
        description="switch to/from hiding mode",
        default=False,
    )
    show_hiding_icon: bpy.props.BoolProperty(
        name="Enable hiding icon",
        description="Disable this if you just don't want that little eye in each window tab area.",
        default=True,
    )
    enable_folding: bpy.props.BoolProperty(
        name="Enable tab panel folding icon",
        description="switch to/from hiding mode",
        default=False,
    )

    enable_disabling: bpy.props.BoolProperty(
        name="Enable tab panel disable for areas",
        description="switch to/from hiding mode",
        default=True,
    )
    disable_UI: bpy.props.BoolProperty(
        name="Disable tabs in UI regions",
        description="switch to/from hiding mode",
        default=False,
    )
    disable_PROPERTIES: bpy.props.BoolProperty(
        name="Disable properties area",
        description="switch to/from hiding mode",
        default=False,
    )
    disable_MODIFIERS: bpy.props.BoolProperty(
        name="Disable for modifiers and constraints",
        description="switch to/from hiding mode",
        default=True,
    )

    panelData: bpy.props.CollectionProperty(type=panelData)
    panelTabData: bpy.props.CollectionProperty(type=tabSetups)
    categories: bpy.props.CollectionProperty(type=tabCategoryData)

    # here you specify how they are drawn
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "emboss")
        layout.prop(self, "box")

        layout.prop(self, "fixed_width")
        if self.fixed_width:
            layout.prop(self, "fixed_columns")
            if self.fixed_columns:
                layout.prop(self, "columns_properties")
                layout.prop(self, "columns_modifiers")
                layout.prop(self, "columns_rest")
        # layout.prop(self, "align_rows")
        if not self.fixed_width:
            layout.prop(self, "scale_y")
        layout.prop(self, "original_panels")
        layout.prop(self, "enable_folding")
        layout.prop(self, "show_hiding_icon")
        layout.prop(self, "enable_disabling")
        if self.enable_disabling:
            b = layout.box()
            b.prop(self, "disable_UI")
            b.prop(self, "disable_PROPERTIES")
            b.prop(self, "disable_MODIFIERS")
        layout.prop(self, "reorder_panels")


def createSceneTabData():
    if DEBUG:
        print("create tab panel data")
    s = bpy.context.window_manager
    # print('handler')
    processpanels = []

    removepanels = []
    for pname in bpy.types.WindowManager.panelIDs:
        if hasattr(bpy.types, pname):
            p = getattr(bpy.types, pname)
            if (
                not hasattr(p, "realID")
                or s.panelData.get(p.realID) is None
                or p not in s.panelSpaces[p.bl_space_type][p.bl_region_type]
            ):
                processpanels.append(p)

        else:
            removepanels.append(pname)

    for pname in removepanels:  # can't pop during iteration, doing afterwards.
        bpy.types.WindowManager.panelIDs.pop(pname)

    if len(processpanels) > 0:
        buildTabDir(processpanels)
    # print('create scene tab data')
    for pname in bpy.types.WindowManager.panelIDs:
        # print('pname')
        if hasattr(bpy.types, pname):
            # print('go on ')
            # print(p.realID)
            p = getattr(bpy.types, pname)
            # TODO following condition should not check for realID...this should be there allready
            if hasattr(p, "realID"):
                if not p.realID in bpy.context.window_manager.panelData:

                    item = bpy.context.window_manager.panelData.add()
                    item.name = p.realID
                    item.space = p.bl_space_type
                    item.region = p.bl_region_type
                    if hasattr(p, "bl_context"):
                        item.context = p.bl_context
                    if hasattr(p, "orig_category"):
                        item.category = p.orig_category
                    if hasattr(p, "bl_parent_id"):
                        item.parent = p.bl_parent_id

                    # item.context = p.bl_region_type

                if hasattr(
                    p, "bl_category"
                ):  # and not (p.bl_region_type == 'UI' and p.bl_space_type == 'VIEW_3D'): #additional checks for Archimesh only!
                    c = s.categories.get(p.orig_category)
                    if c is None:
                        # print(p.orig_category)
                        c = s.categories.add()
                        c.name = p.orig_category
            else:
                pass
                # print('unprocessed without realID', p)

    while len(_update_tabs) > 0:
        pt = _update_tabs.pop()
        print("Tabs interface: updating  ", pt)
        # print( r.panelTabData)
        # print( s.panelTabData.get(pt.bl_rna.identifier))
        pname = pt.bl_rna.identifier

        if s.panelTabData.get(pname) is None:
            item = s.panelTabData.add()
            item.name = pname

    while len(_update_categories) > 0:
        cname = _update_categories.pop()
        c = s.categories.get(p.bl_category)
        if c is None:
            c = s.categories.add()
            c.name = cname

    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type != "INFO":
                for r in a.regions:
                    with bpy.context.temp_override(window=w, area=a, region=r):
                        bpy.ops.view2d.scroll_up(deltax=0, deltay=5000)

                    # print(r.type)
                    r.tag_redraw()
                a.tag_redraw()


def overrideDrawFunctions():
    prefs = bpy.context.preferences.addons[__package__].preferences
    s = bpy.context.window_manager
    if s.get("functions_overwrite_success") is None:
        s["functions_overwrite_success"] = False
    if not s["functions_overwrite_success"]:
        if prefs.disable_MODIFIERS:
            s["functions_overwrite_success"] = True
            return
        try:
            bpy.types.DATA_PT_modifiers.draw = modifiersDraw
            bpy.types.OBJECT_PT_constraints.draw = constraintsDraw
            bpy.types.BONE_PT_constraints.draw = boneConstraintsDraw
            s["functions_overwrite_success"] = True
        except Exception as e:
            print(f"tabs_interface: could not override modifier/constraint draw: {e}")


@persistent
def tab_init_handler(scene):
    s = bpy.context.window_manager

    allpanels = getPanelIDs()
    if len(bpy.types.WindowManager.panelSpaces) == 0:
        bpy.types.WindowManager.panelSpaces = buildTabDir(allpanels)

    btypeslen = len(dir(bpy.types))
    if btypeslen != s.get("bpy_types_len"):
        updatePanels()
    s["bpy_types_len"] = btypeslen
    createSceneTabData()
    s["functions_overwrite_success"] = False
    overrideDrawFunctions()

    # Timers are cleared on file load — re-register if needed
    if not bpy.app.timers.is_registered(tab_update_handler):
        bpy.app.timers.register(tab_update_handler)


@persistent
def tab_update_handler(scene=None):
    """check periodically for panels that were not processed yet."""

    s = bpy.context.window_manager
    sc = s.get("tabs_update_counter")
    first = False
    if sc is None:
        first = True
        sc = s["tabs_update_counter"] = 0

    s["tabs_update_counter"] += 1
    # if sc > 5 or first:  # this should be replaced by better detecting if registrations might have changed.
    s["tabs_update_counter"] = 0
    # t = time.time()

    btypeslen = len(dir(bpy.types))
    if btypeslen != s.get("bpy_types_len") or first:
        updatePanels()
    s["bpy_types_len"] = btypeslen

    overrideDrawFunctions()

    if len(_update_tabs) > 0 or first:
        createSceneTabData()

    while len(_extra_activations) > 0:
        p = _extra_activations.pop()
        bpy.context.window_manager.panelData[p.realID].activated = True

    return 1


def register():
    bpy.utils.register_class(tabSetups)
    bpy.utils.register_class(panelData)
    bpy.utils.register_class(tabCategoryData)
    bpy.utils.register_class(TabInterfacePreferences)
    bpy.utils.register_class(PanelUp)
    bpy.utils.register_class(PanelDown)
    bpy.utils.register_class(WritePanelOrder)
    bpy.utils.register_class(ActivatePanel)
    bpy.utils.register_class(ActivateCategory)
    bpy.utils.register_class(ActivateModifier)
    bpy.utils.register_class(ActivateConstraint)
    bpy.utils.register_class(ActivatePoseBoneConstraint)

    bpy.types.Object.active_modifiers = (
        []
    )  # bpy.props.StringProperty(name = 'active modifier', default = '')
    bpy.types.Object.active_constraints = (
        []
    )  # bpy.props.StringProperty(name = 'active constraint', default = '')
    bpy.types.PoseBone.active_constraints = (
        []
    )  # bpy.props.StringProperty(name = 'active constraint', default = '')

    bpy.types.WindowManager.panelData = bpy.props.CollectionProperty(type=panelData)
    bpy.types.WindowManager.panelTabData = bpy.props.CollectionProperty(type=tabSetups)
    bpy.types.WindowManager.categories = bpy.props.CollectionProperty(
        type=tabCategoryData
    )

    bpy.app.handlers.load_post.append(tab_init_handler)
    bpy.app.handlers.load_post.append(tab_update_handler)
    bpy.app.timers.register(tab_update_handler)

    allpanels = getPanelIDs()
    bpy.types.WindowManager.panelSpaces = buildTabDir(allpanels)

    definitions, panelIDs = createPanels()
    for d in definitions:
        exec(d)
    for pname in panelIDs:
        p = eval(pname)
        bpy.utils.register_class(eval(pname))


def unregister():
    for panel in bpy.types.WindowManager.panelIDs:

        if hasattr(panel, "bl_category"):
            if hasattr(panel, "orig_category"):
                panel.bl_category = panel.orig_category

        fixOriginalPanel(panel)

    definitions, panelIDs = createPanels()
    for d in definitions:
        exec(d)
    for pname in panelIDs:
        if hasattr(bpy.types, pname):
            bpy.utils.unregister_class(getattr(bpy.types, pname))

    bpy.utils.unregister_class(PanelUp)
    bpy.utils.unregister_class(PanelDown)
    bpy.utils.unregister_class(WritePanelOrder)
    bpy.utils.unregister_class(ActivatePanel)
    bpy.utils.unregister_class(ActivateCategory)
    bpy.utils.unregister_class(ActivateModifier)
    bpy.utils.unregister_class(ActivateConstraint)
    bpy.utils.unregister_class(ActivatePoseBoneConstraint)
    bpy.utils.unregister_class(tabSetups)
    bpy.utils.unregister_class(panelData)
    bpy.utils.unregister_class(tabCategoryData)
    bpy.utils.unregister_class(TabInterfacePreferences)

    bpy.app.handlers.load_post.remove(tab_init_handler)
    bpy.app.handlers.load_post.remove(tab_update_handler)
    bpy.app.timers.unregister(tab_update_handler)

    del bpy.types.WindowManager.panelSpaces
    del bpy.types.WindowManager.panelIDs


if __name__ == "__main__":
    register()
