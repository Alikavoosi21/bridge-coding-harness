'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { Mode } from './api';

export type SettingsTab = 'general' | 'models' | 'workspace' | 'readiness' | 'data';

/** What the user has chosen for the next message; remembered across screens. */
export type RunOptions = { modelId?: string; agentId?: string | null; mode: Mode };

/** Pure interface state. Everything that comes from the backend lives in `backend.ts`. */
type UiState = {
  sidebarOpen: boolean;
  toggleSidebar: () => void;

  /** The task open on the tasks screen; null means "new task". */
  activeThread: string | null;
  setActiveThread: (threadId: string | null) => void;

  runOptions: RunOptions;
  setRunOptions: (options: Partial<RunOptions>) => void;

  /** Workspace path of the file open in the files screen. */
  openFile: string | null;
  setOpenFile: (path: string | null) => void;

  /** Which settings section is open, so other screens can link straight to one. */
  settingsTab: SettingsTab;
  setSettingsTab: (tab: SettingsTab) => void;

  /**
   * The unsent text of the home composer, kept per workspace folder.
   *
   * Switching folders must not silently throw away what someone typed, and it
   * must not silently move it either: the dialog in the sidebar asks. Only the
   * text is stored here; file references never follow a project change on their
   * own, because a path means something different in another folder.
   */
  drafts: Record<string, string>;
  setDraft: (workspace: string, text: string) => void;

  /** The introduction, reopened on request (it opens by itself on first launch). */
  introOpen: boolean;
  setIntroOpen: (open: boolean) => void;

  /** Reopen the four-step setup wizard after it was completed, to review or change it. */
  setupOpen: boolean;
  setSetupOpen: (open: boolean) => void;
};

export const useUi = create<UiState>()(persist((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  activeThread: null,
  setActiveThread: (activeThread) => set({ activeThread }),

  runOptions: { mode: 'ask' },
  setRunOptions: (options) => set((s) => ({ runOptions: { ...s.runOptions, ...options } })),

  openFile: null,
  setOpenFile: (openFile) => set({ openFile }),

  settingsTab: 'general',
  setSettingsTab: (settingsTab) => set({ settingsTab }),

  drafts: {},
  setDraft: (workspace, text) =>
    set((s) => {
      if (!workspace) return s;
      if ((s.drafts[workspace] ?? '') === text) return s;
      return { drafts: { ...s.drafts, [workspace]: text } };
    }),

  introOpen: false,
  setIntroOpen: (introOpen) => set({ introOpen }),

  setupOpen: false,
  setSetupOpen: (setupOpen) => set({ setupOpen }),
}),{name:'bridge-chat-drafts',partialize:state=>({drafts:state.drafts}),skipHydration:true}));
