import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import { Loader } from "./components/ui";
import NationalHome from "./pages/ministry/NationalHome";
import PlanCrops from "./pages/ministry/PlanCrops";
import Reserves from "./pages/ministry/Reserves";
import AlertsManagement from "./pages/ministry/AlertsManagement";
import Terrain from "./pages/farmer/Terrain";
import MyPlan from "./pages/farmer/MyPlan";
import WaterEnergy from "./pages/farmer/WaterEnergy";
import Harvest from "./pages/farmer/Harvest";
import { FarmProvider } from "./lib/farm";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Loader />;
  if (!user) return <Login />;
  if (user.role === "ministry") {
    return (
      <Routes>
        <Route element={<Layout />}>
          <Route path="/ministry" element={<NationalHome />} />
          <Route path="/ministry/plan" element={<PlanCrops />} />
          <Route path="/ministry/reserves" element={<Reserves />} />
          <Route path="/ministry/alerts" element={<AlertsManagement />} />
          <Route path="*" element={<Navigate to="/ministry" replace />} />
        </Route>
      </Routes>
    );
  }
  return (
    <FarmProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/farm" element={<Terrain />} />
          <Route path="/farm/plan" element={<MyPlan />} />
          <Route path="/farm/water" element={<WaterEnergy />} />
          <Route path="/farm/harvest" element={<Harvest />} />
          <Route path="*" element={<Navigate to="/farm" replace />} />
        </Route>
      </Routes>
    </FarmProvider>
  );
}
