import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import './MainLayout.css';

/**
 * Main application layout with collapsible sidebar and content area.
 *
 * The sidebar contains navigation links to all major sections.
 * Content is rendered via React Router's <Outlet />.
 */

interface NavItem {
  to: string;
  icon: string;
  label: string;
}

const navItems: NavItem[] = [
  { to: '/dashboard', icon: '📊', label: 'Dashboard' },
  { to: '/containers', icon: '🐳', label: 'Containers' },
  { to: '/marketplace', icon: '🛒', label: 'Marketplace' },
  { to: '/domains', icon: '🌐', label: 'Domains' },
  { to: '/backup', icon: '💾', label: 'Backup' },
  { to: '/security', icon: '🔒', label: 'Security' },
  { to: '/settings', icon: '⚙️', label: 'Settings' },
];

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`layout ${collapsed ? 'layout--collapsed' : ''}`}>
      {/* Sidebar */}
      <aside className="sidebar" role="navigation" aria-label="Main navigation">
        <div className="sidebar__header">
          <div className="sidebar__logo">
            <span className="sidebar__logo-icon">🏠</span>
            {!collapsed && <span className="sidebar__logo-text">Homelab</span>}
          </div>
          <button
            className="sidebar__toggle"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '→' : '←'}
          </button>
        </div>

        <nav className="sidebar__nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `sidebar__link ${isActive ? 'sidebar__link--active' : ''}`
              }
              title={item.label}
            >
              <span className="sidebar__link-icon">{item.icon}</span>
              {!collapsed && <span className="sidebar__link-label">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          {!collapsed && (
            <div className="sidebar__version">
              <span className="badge badge-info">v0.1.0</span>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <main className="content">
        <div className="content__inner animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
