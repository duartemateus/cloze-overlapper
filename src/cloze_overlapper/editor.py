# -*- coding: utf-8 -*-

# Cloze Overlapper Add-on for Anki
#
# Copyright (C)  2016-2019 Aristotelis P. <https://glutanimate.com/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the accompanied license file.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License which
# accompanied this program.
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.

"""
Additions to Anki's note editor
"""

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import re

from anki.hooks import wrap, addHook

from aqt.qt import *
from aqt.editor import Editor
from aqt.addcards import AddCards
from aqt.editcurrent import EditCurrent
from aqt.utils import tooltip, showInfo

from .libaddon.platform import ANKI21

from .overlapper import ClozeOverlapper
from .gui.options_note import OlcOptionsNote
from .template import checkModel
from .config import config
from .utils import showTT


# Hotkey definitions

olc_hotkey_generate = "Alt+Shift+C"  # Cloze generation/preview
olc_hotkey_settings = "Alt+Shift+O"  # Note-specific settings
olc_hotkey_cremove = "Alt+Shift+U"  # Remove selected clozes
olc_hotkey_olist = "Ctrl+Alt+Shift+."  # Toggle ordered list
olc_hotkey_ulist = "Ctrl+Alt+Shift+,"  # Toggle unordered list
olc_hotkey_mcloze = "Ctrl+Shift+K"  # Multi-line cloze
olc_hotkey_mclozealt = "Ctrl+Alt+Shift+K"  # Multi-line cloze alt

# Javascript

js_cloze_multi = """
var increment = %s;
var highest = %d;
function clozeChildren(container) {
    children = container.childNodes
    for (i = 0; i < children.length; i++) {
        var child = children[i]
        var contents = child.innerHTML
        var textOnly = false;
        if (typeof contents === 'undefined'){
            // handle text nodes
            var contents = child.textContent
            textOnly = true;}
        if (increment){idx = highest+i} else {idx = highest}
        contents = '%s' + idx + '::' + contents + '%s'
        if (textOnly){
            child.textContent = contents}
        else {
            child.innerHTML = contents}}
}
if (typeof window.getSelection != "undefined") {
    // get selected HTML
    var sel = window.getSelection();
    if (sel.rangeCount) {
        var container = document.createElement("div");
        for (var i = 0, len = sel.rangeCount; i < len; ++i) {
            container.appendChild(sel.getRangeAt(i).cloneContents());}}
    // wrap each topmost child with cloze tags; TODO: Recursion
    clozeChildren(container);
    // workaround for duplicate list items:
    var clozed = container.innerHTML.replace(/^(<li>)/, "")
    document.execCommand('insertHTML', false, clozed);
    saveField('key');
}
"""

js_cloze_remove = """
function getSelectionHtml() {
    // Based on an SO answer by Tim Down
    var html = "";
    if (typeof window.getSelection != "undefined") {
        var sel = window.getSelection();
        if (sel.rangeCount) {
            var container = document.createElement("div");
            for (var i = 0, len = sel.rangeCount; i < len; ++i) {
                container.appendChild(sel.getRangeAt(i).cloneContents());
            }
            html = container.innerHTML;
        }
    } else if (typeof document.selection != "undefined") {
        if (document.selection.type == "Text") {
            html = document.selection.createRange().htmlText;
        }
    }
    return html;
}
if (typeof window.getSelection != "undefined") {
    // get selected HTML
    var sel = getSelectionHtml();
    sel = sel.replace(/%s/mg, "$2");
    // workaround for duplicate list items:
    var sel = sel.replace(/^(<li>)/, "")
    document.execCommand('insertHTML', false, sel);
    saveField('key');
}
"""

# EDITOR

# Button callbacks


def onInsertCloze(self, _old):
    """Handles cloze-wraps when the add-on model is active"""
    if not checkModel(self.note.model(), fields=False, notify=False):
        return _old(self)
    # find the highest existing cloze
    highest = 0
    for name, val in self.note.items():
        m = re.findall("\[\[oc(\d+)::", val)
        if m:
            highest = max(highest, sorted([int(x) for x in m])[-1])
    # reuse last?
    if not self.mw.app.keyboardModifiers() & Qt.AltModifier:
        highest += 1
    # must start at 1
    highest = max(1, highest)
    self.web.eval("wrap('[[oc%d::', ']]');" % highest)


def onInsertMultipleClozes(self):
    """Wraps each line in a separate cloze"""
    model = self.note.model()
    # check that the model is set up for cloze deletion
    if not re.search('{{(.*:)*cloze:', model['tmpls'][0]['qfmt']):
        if self.addMode:
            tooltip(_("Warning, cloze deletions will not work until "
                      "you switch the type at the top to Cloze."))
        else:
            showInfo(_("""\
To make a cloze deletion on an existing note, you need to change it \
to a cloze type first, via Edit>Change Note Type."""))
            return
    if checkModel(model, fields=False, notify=False):
        cloze_re = "\[\[oc(\d+)::"
        wrap_pre, wrap_post = "[[oc", "]]"
    else:
        cloze_re = "\{\{c(\d+)::"
        wrap_pre, wrap_post = "{{c", "}}"
    # find the highest existing cloze
    highest = 0
    for name, val in self.note.items():
        m = re.findall(cloze_re, val)
        if m:
            highest = max(highest, sorted([int(x) for x in m])[-1])
    increment = "false"
    if not self.mw.app.keyboardModifiers() & Qt.AltModifier:
        highest += 1
        increment = "true"
    highest = max(1, highest)
    # process selected text
    self.web.eval(js_cloze_multi % (
        increment, highest, wrap_pre, wrap_post))


def onRemoveClozes(self):
    """Remove cloze markers and hints from selected text"""
    if checkModel(self.note.model(), fields=False, notify=False):
        cloze_re = r"\[\[oc(\d+)::(.*?)(::(.*?))?\]\]"
    else:
        cloze_re = r"\{\{c(\d+)::(.*?)(::(.*?))?\}\}"
    self.web.eval(js_cloze_remove % cloze_re)


def onOlOptionsButton(self):
    """Invoke note-specific options dialog"""
    if not checkModel(self.note.model()):
        return False
    options = OlcOptionsNote(self.parentWindow)
    options.exec_()


def onOlClozeButton(self, markup=None, parent=None):
    """Invokes an instance of the main add-on class"""
    if not checkModel(self.note.model()):
        return False
    overlapper = ClozeOverlapper(self, markup=markup, parent=parent)
    overlapper.add()


# Patching buttons in

def setupAdditionalHotkeys(editor):
    add_ol_cut = QShortcut(QKeySequence(_(olc_hotkey_olist)), editor.widget)
    add_ol_cut.activated.connect(lambda o="ol": onOlClozeButton(editor, o))
    add_ul_cut = QShortcut(QKeySequence(_(olc_hotkey_ulist)), editor.widget)
    add_ul_cut.activated.connect(lambda o="ul": onOlClozeButton(editor, o))

    mult_cloze_cut1 = QShortcut(QKeySequence(
        _(olc_hotkey_mcloze)), editor.widget)
    mult_cloze_cut1.activated.connect(lambda: onInsertMultipleClozes(editor))
    mult_cloze_cut2 = QShortcut(QKeySequence(
        _(olc_hotkey_mclozealt)), editor.widget)
    mult_cloze_cut2.activated.connect(lambda: onInsertMultipleClozes(editor))


def onSetupEditorButtons20(editor):
    """Add buttons and hotkeys to the editor widget"""

    b = editor._addButton("Cloze Overlapper",
                          editor.onOlClozeButton, _(olc_hotkey_generate),
                          "Generate overlapping clozes (%s)" % _(
                              olc_hotkey_generate),
                          text="[.]]", size=True)
    b.setFixedWidth(24)

    b = editor._addButton("Cloze Overlapper Note Settings",
                          editor.onOlOptionsButton, _(olc_hotkey_settings),
                          "Overlapping cloze generation settings (%s)" % _(
                              olc_hotkey_settings),
                          text="[O]", size=True)
    b.setFixedWidth(24)

    b = editor._addButton("Remove Clozes",
                          editor.onRemoveClozes, _(olc_hotkey_cremove),
                          "Remove all cloze markers<br>in selected text (%s)" % _(
                              olc_hotkey_cremove),
                          text="rc", size=True)
    b.setFixedWidth(24)

    setupAdditionalHotkeys(editor)


def onSetupEditorButtons21(buttons, editor):
    """Add buttons and hotkeys"""

    b = editor.addButton("", "OlCloze", onOlClozeButton,
                         "Generate overlapping clozes (%s)" % _(
                             olc_hotkey_generate),
                         "[.]]", keys=olc_hotkey_generate)
    buttons.append(b)

    b = editor.addButton("", "OlOptions", onOlOptionsButton,
                         "Overlapping cloze generation settings (%s)" % _(
                             olc_hotkey_settings),
                         "[O]", keys=olc_hotkey_settings)
    buttons.append(b)

    b = editor.addButton("", "RemoveClozes", onRemoveClozes,
                         "Remove all cloze markers in selected text (%s)" % _(
                             olc_hotkey_cremove),
                         "rc", keys=olc_hotkey_cremove)
    buttons.append(b)

    setupAdditionalHotkeys(editor)

    return buttons


# ADDCARDS / EDITCURRENT

# Callbacks

def onAddCards(self, _old):
    """Automatically generate overlapping clozes before adding cards"""
    note = self.editor.note
    if not note or not checkModel(note.model(), notify=False):
        return _old(self)
    overlapper = ClozeOverlapper(self.editor, silent=True)
    ret, total = overlapper.add()
    if not ret:
        return
    oldret = _old(self)
    if total:
        showTT("Info", "Added %d overlapping cloze cards" % total, period=1000)
    return oldret


def onEditCurrent(self, _old):
    """Automatically update overlapping clozes before updating cards"""
    note = self.editor.note
    if not note or not checkModel(note.model(), notify=False):
        return _old(self)
    overlapper = ClozeOverlapper(self.editor, silent=True)
    ret, total = overlapper.add()
    # returning here won't stop the window from being rejected, so we simply
    # accept whatever changes the user performed, even if the generator
    # did not fire
    oldret = _old(self)
    if total:
        showTT("Info", "Updated %d overlapping cloze cards" %
               total, period=1000)
    return oldret


def onAddNote(self, note, _old):
    """Suspend full cloze card if option active"""
    note = _old(self, note)
    if not note or not checkModel(note.model(), fields=False, notify=False):
        return note
    sched_conf = config["synced"].get("sched", None)
    if not sched_conf or not sched_conf[2]:
        return note
    maxfields = ClozeOverlapper.getMaxFields(
        note.model(), config["synced"]["flds"]["tx"])
    last = note.cards()[-1]
    if last.ord == maxfields:  # is full cloze (ord starts at 0)
        mw.col.sched.suspendCards([last.id])
    return note

# MAIN


def initializeEditor():
    # Editor widget
    Editor.onCloze = wrap(Editor.onCloze, onInsertCloze, "around")
    if not ANKI21:
        Editor.onOlClozeButton = onOlClozeButton
        Editor.onOlOptionsButton = onOlOptionsButton
        Editor.onInsertMultipleClozes = onInsertMultipleClozes
        Editor.onRemoveClozes = onRemoveClozes
        addHook("setupEditorButtons", onSetupEditorButtons20)
    else:
        addHook("setupEditorButtons", onSetupEditorButtons21)

    # AddCard / EditCurrent windows
    AddCards.addCards = wrap(AddCards.addCards, onAddCards, "around")
    AddCards.addNote = wrap(AddCards.addNote, onAddNote, "around")
    if not ANKI21:
        EditCurrent.onSave = wrap(EditCurrent.onSave, onEditCurrent, "around")
    else:
        EditCurrent._saveAndClose = wrap(EditCurrent._saveAndClose,
                                         onEditCurrent, "around")