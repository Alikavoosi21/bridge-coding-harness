export {};

declare global {
  interface Window {
    desktop?: {
      isDesktop: boolean;
      platform: string;
      api?: { url: string; token: string };
      setTheme: (theme: 'light' | 'dark') => void;
      pickFolder?: () => Promise<string | null>;
      /** Opens a file or folder of the workspace. Resolves to '' when opened, otherwise to the reason it was not. */
      openPath?: (path: string) => Promise<'' | 'outside' | 'missing' | 'runnable' | 'failed'>;
      openPreview?: (taskId:string,outputId:string) => Promise<boolean>;
    };
  }
}

