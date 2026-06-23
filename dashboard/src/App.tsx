import { AuthProvider, useAuth } from "./AuthContext";
import { LoginPage } from "./LoginPage";
import { Dashboard } from "./Dashboard";
import "./App.css";

function AppContent() {
  const { token } = useAuth();
  return token ? <Dashboard /> : <LoginPage />;
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
