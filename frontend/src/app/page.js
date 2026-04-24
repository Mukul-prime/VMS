"use client";

import { useEffect, useState, useRef } from "react";

const BASE_URL = "http://127.0.0.1:8000";

function CameraFeed({ cam, onClick }) {
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef(null);

  // ✅ cam.Cam_id
  const streamUrl = `${BASE_URL}/streams/${cam.Cam_id}/`;

  const retryStream = (e) => {
    e.stopPropagation();
    setError(false);
    if (imgRef.current) {
      imgRef.current.src = `${streamUrl}`;
    }
  };

  return (
    <div
      className="relative rounded-xl overflow-hidden cursor-pointer group border border-gray-200 shadow-md bg-black"
      onClick={onClick}
      style={{ aspectRatio: "16/9" }}
    >
      {/* ✅ img tag — iframe nahi */}
      {!error && (
        <img
          ref={imgRef}
          src={streamUrl}
          alt={cam.Cam_name}
          onError={() => { setError(true); setLoaded(false); }}
          onLoad={() => { setLoaded(true); setError(false); }}
          className="w-full h-full object-cover"
          style={{ display: loaded ? "block" : "none" }}
        />
      )}

      {/* Loading */}
      {!loaded && !error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-900 text-white gap-2">
          <div className="w-8 h-8 border-4 border-blue-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs text-gray-400">Connecting...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-900 text-white gap-3">
          <span className="text-3xl">📷</span>
          <p className="text-sm text-gray-400">Stream unavailable</p>
          <button
            onClick={retryStream}
            className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1.5 rounded-full"
          >
            Retry
          </button>
        </div>
      )}

      {/* LIVE Badge */}
      {loaded && !error && (
        <span className="absolute top-2 left-2 bg-red-500 text-white text-xs px-2 py-1 rounded-full flex items-center gap-1">
          <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
          LIVE
        </span>
      )}

      {/* Camera Name */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black to-transparent px-3 py-2">
        <p className="text-white text-sm font-semibold truncate">{cam.Cam_name}</p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [cameras, setCameras] = useState([]);
  const [activeCam, setActiveCam] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BASE_URL}/cameras/`)
      .then((res) => res.json())
      .then((data) => {
        setCameras(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Fetch error:", err);
        setLoading(false);
      });
  }, []);

  // ✅ Cam_id se match karo
  const activeCamData = cameras.find((c) => c.Cam_id === activeCam);

  return (
    <div className="p-6 bg-gradient-to-br from-gray-100 to-gray-200 min-h-screen">

      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🎥 VMS Dashboard</h1>
        <span className="bg-green-100 text-green-700 px-3 py-1 rounded-full text-sm flex items-center gap-1">
          <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          Live
        </span>
      </div>

      {/* Stats */}
      <div className="grid md:grid-cols-3 gap-6 mb-6">
        <div className="bg-white p-5 rounded-xl shadow">
          <p className="text-gray-500">Total Cameras</p>
          <h2 className="text-3xl font-bold text-blue-600">{cameras.length}</h2>
        </div>
        <div className="bg-white p-5 rounded-xl shadow">
          <p className="text-gray-500">Active Cameras</p>
          <h2 className="text-3xl font-bold text-green-600">{cameras.length}</h2>
        </div>
        <div className="bg-white p-5 rounded-xl shadow">
          <p className="text-gray-500">Status</p>
          <h2 className="text-green-600 font-bold">
            {loading ? "Loading..." : "✅ Running"}
          </h2>
        </div>
      </div>

      {/* Live Cameras Grid */}
      <div className="bg-white p-5 rounded-xl shadow mb-6">
        <h2 className="text-xl font-semibold mb-4">Live Cameras</h2>

        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 gap-2">
            <div className="w-6 h-6 border-4 border-blue-400 border-t-transparent rounded-full animate-spin" />
            Loading cameras...
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cameras.map((cam) => (
              <CameraFeed
                key={cam.Cam_id}
                cam={cam}
                onClick={() => setActiveCam(cam.Cam_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Camera List */}
      <div className="bg-white p-5 rounded-xl shadow">
        <h2 className="text-xl font-semibold mb-4">Camera List</h2>
        <div className="grid md:grid-cols-2 gap-4">
          {cameras.map((cam) => (
            <div
              key={cam.Cam_id}
              className="p-4 border rounded-lg flex justify-between items-center hover:bg-gray-50 cursor-pointer"
              onClick={() => setActiveCam(cam.Cam_id)}
            >
              <div>
                <h3 className="font-bold">{cam.Cam_name}</h3>
                <p className="text-sm text-gray-500">ID: {cam.Cam_id}</p>
                <p className="text-xs text-gray-400">{cam.Cam_location}</p>
              </div>
              <span className="text-green-500 text-sm flex items-center gap-1">
                <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                Active
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Fullscreen Modal */}
      {activeCam !== null && activeCamData && (
        <div
          className="fixed inset-0 bg-black bg-opacity-90 flex flex-col items-center justify-center z-50"
          onClick={() => setActiveCam(null)}
        >
          <div
            className="relative w-[90vw] max-w-5xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-white text-lg font-bold">{activeCamData.Cam_name}</h3>
              <button
                className="text-white bg-white bg-opacity-20 hover:bg-opacity-30 rounded-full w-8 h-8 flex items-center justify-center"
                onClick={() => setActiveCam(null)}
              >
                ✕
              </button>
            </div>

            {/* eslint-disable-next-line react-hooks/purity */}
            <img
                src={`${BASE_URL}/streams/${activeCam}/`}
                alt="camera"
                className="w-full rounded-xl border border-white border-opacity-20"
                style={{ maxHeight: "80vh", objectFit: "contain" }}
            />

            <p className="text-gray-400 text-xs text-center mt-2">
              Bahar click karo band karne ke liye
            </p>
          </div>
        </div>
      )}
    </div>
  );
}