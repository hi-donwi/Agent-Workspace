import { createRoot } from 'react-dom/client';
import 'uidl-runtime/style.css';
import './styles.css';
import { App } from './app';
import { RenderBoundary } from './ui';

createRoot(document.getElementById('root')!).render(<RenderBoundary><App /></RenderBoundary>);
