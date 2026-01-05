import type { MindElixirInstance } from '../types/index';
import './contextMenu.less';
export type ContextMenuOption = {
    focus?: boolean;
    link?: boolean;
    extend?: {
        name: string;
        key?: string;
        onclick: (e: MouseEvent) => void;
    }[];
};
export default function (mind: MindElixirInstance, option: true | ContextMenuOption): () => void;
