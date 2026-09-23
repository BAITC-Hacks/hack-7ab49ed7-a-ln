import { loginDestination } from './loginDestination';
import { Component, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client';
import { useMeta } from './hooks/queries';
import { ErrorView, Loading } from './components/Common';
import { CAUTION } from './format';
import s from './App.module.css';

export function AppShell() {
  const meta = useMeta();
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const session = useQuery({
    queryKey: ['session'],
    queryFn: ({ signal }) => api.session(signal),
    enabled: !!meta.data?.auth_required,
    staleTime: 30_000,
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      client.clear();
      navigate('/login', { replace: true });
    },
  });
  useEffect(() => {
    const expired = () => {
      void client.cancelQueries();
      client.clear();
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
    };
    window.addEventListener('mg:unauthorized', expired);
    return () => window.removeEventListener('mg:unauthorized', expired);
  }, [client, navigate, location.pathname, location.search]);
  if (meta.isPending || (meta.data?.auth_required && session.isPending))
    return <Loading label="Подключение к рабочему пространству…" />;
  if (meta.error || session.error)
    return (
      <div className={s.fatal}>
        <ErrorView
          error={meta.error ?? session.error}
          retry={() => {
            void meta.refetch();
            if (meta.data?.auth_required) void session.refetch();
          }}
        />
      </div>
    );
  const authenticated = !meta.data?.auth_required || session.data?.authenticated;
  if (authenticated && location.pathname === '/login')
    return <Navigate to={loginDestination(location.search)} replace />;
  if (!authenticated && location.pathname !== '/login')
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  return (
    <div className={s.shell}>
      <a href="#main" className={s.skip}>
        Перейти к содержимому
      </a>
      {import.meta.env.VITE_MOCK_API === 'true' && (
        <div className={s.mock}>Демонстрационный режим · синтетические данные · API эмулируется</div>
      )}
      <header className={s.nav}>
        <NavLink className={s.brand} to="/runs">
          <span className={s.mark} aria-hidden>
            ⠿
          </span>
          Граф денег
        </NavLink>
        <NavLink className={s.navLink} to="/runs">
          Исследования
        </NavLink>
        <NavLink className={s.navLink} to="/methodology">
          Методология
        </NavLink>
        <div className={s.right}>
          <span className={s.live}>Рабочее пространство аналитика</span>
          {meta.data?.auth_required && authenticated && (
            <button onClick={() => logout.mutate()} disabled={logout.isPending}>
              Выйти
            </button>
          )}
        </div>
      </header>
      {logout.error && <ErrorView error={logout.error} />}
      <main id="main" className={s.main}>
        <Outlet />
      </main>
      <footer className={s.footer}>
        <span>{CAUTION}</span>
        <span>MoneyGraph · {meta.data?.version}</span>
      </footer>
    </div>
  );
}
export function LoginPage() {
  const [token, setToken] = useState('');
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const meta = useMeta();
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: async () => {
      setToken('');
      await client.invalidateQueries({ queryKey: ['session'] });
      navigate(loginDestination(location.search), { replace: true });
    },
  });
  if (meta.data && !meta.data.auth_required) return <Navigate to="/runs" replace />;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate(token);
  };
  return (
    <section className={s.login}>
      <span>ЗАЩИЩЁННОЕ ПРОСТРАНСТВО</span>
      <h1>Вход для аналитика</h1>
      <p>Введите токен доступа, выданный администратором.</p>
      <form onSubmit={submit}>
        <label>
          Токен доступа
          <input
            autoFocus
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
        </label>
        {login.error && <ErrorView error={login.error} />}
        <button className="primary" disabled={!token.trim() || login.isPending}>
          {login.isPending ? 'Проверка…' : 'Войти'}
        </button>
      </form>
      <p>
        <small>Сессия хранится в защищённой cookie. Токен не сохраняется в браузерном хранилище.</small>
      </p>
    </section>
  );
}
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    return this.state.error ? (
      <div className={s.fatal}>
        <h1>Не удалось отобразить страницу</h1>
        <p>Перезагрузите страницу. Если ошибка повторится, обратитесь к администратору.</p>
        <button onClick={() => window.location.reload()}>Перезагрузить</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
