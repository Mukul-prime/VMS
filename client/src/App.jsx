import { useState, useRef } from "react";
import Webcam from "react-webcam";
import axios from "axios";

function App() {
  const webcamRef = useRef(null);

  const [form, setForm] = useState({
    name: "",
    email: "",
  });

  const [errors, setErrors] = useState({});
  const [image, setImage] = useState(null);
  const [cameraOn, setCameraOn] = useState(false);

  // ✅ Strict validation
  const validate = () => {
    let newErrors = {};

    if (!form.name.trim()) {
      newErrors.name = "Name is required";
    }

    if (!form.email) {
      newErrors.email = "Email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      newErrors.email = "Enter valid email";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // 📸 Capture
  const capture = () => {
    const imgSrc = webcamRef.current.getScreenshot();
    setImage(imgSrc);
    setCameraOn(false);
  };

  // 🎯 Open Camera ONLY if valid
  const handleOpenCamera = () => {
    if (validate()) {
      setCameraOn(true);
    }
  };

  // 🚀 Submit
const handleSubmit = async () => {
  if (!validate() || !image) {
    alert("Complete all steps properly!");
    return;
  }

  try {
    // ✅ FIX: formData create karo
    const formData = new FormData();

    // base64 image → file convert (IMPORTANT)
    const blob = await fetch(image).then(res => res.blob());
    const file = new File([blob], "capture.jpg", { type: "image/jpeg" });

    // append data
    formData.append("Name", form.name);
    formData.append("Email", form.email);
    formData.append("Image", file);

    await axios.post(
      "http://127.0.0.1:8000/create-user/",
      formData,
      
    );
    console.log(file);
    

    alert("Saved Successfully ✅");

    setForm({ name: "", email: "" });
    setImage(null);
    setCameraOn(false);
  } catch (err) {
    console.error(err);
  }
};

  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email);

  return (
    <div className="min-h-screen flex items-center justify-center bg-linear-to-br from-indigo-500  to-blue-300 px-4">
      <div className="w-full max-w-md bg-white/70 backdrop-blur-xl border border-gray-400 shadow-2xl rounded-3xl p-6 md:p-8">
        {/* HEADER */}
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-gray-800">Smart Capture</h1>
        </div>

        {/* NAME */}
        <div className="mb-4">
          <div className="relative mt-1">
            <input
              type="text"
              placeholder="Enter Full Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-600 focus:ring-2 focus:ring-indigo-500 outline-none"
            />
          </div>
          {errors.name && (
            <p className="text-red-500 text-xs mt-1">{errors.name}</p>
          )}
        </div>

        {/* EMAIL */}
        <div className="mb-4">
          <input
            type="email"
            placeholder="example@gmail.com"
            value={form.email}
            disabled={!form.name}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className={`w-full mt-1 px-4 py-2.5 rounded-xl border outline-none transition
            ${
              !form.name
                ? "bg-gray-300 cursor-not-allowed"
                : "border-black  focus:ring-2 focus:ring-indigo-500"
            }`}
          />
          {errors.email && (
            <p className="text-red-500 text-xs mt-1">{errors.email}</p>
          )}
        </div>

        {/* CAMERA BUTTON */}
        <button
          onClick={handleOpenCamera}
          disabled={!form.name || !isEmailValid}
          className={`w-full py-2.5 rounded-xl font-medium text-white transition-all duration-200
          ${
            form.name && isEmailValid
              ? "bg-indigo-500 hover:bg-indigo-600 shadow-md"
              : "bg-gray-400 cursor-not-allowed"
          }`}
        >
          Open Camera
        </button>

        {/* CAMERA */}
        {cameraOn && (
          <div className="mt-5 p-4 bg-gray-50 rounded-2xl shadow-inner flex flex-col items-center gap-3">
            <Webcam
              ref={webcamRef}
              screenshotFormat="image/jpeg"
              className="rounded-xl border shadow w-full"
            />

            <button
              onClick={capture}
              className="w-full py-2 rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 transition"
            >
              📸 Cap ture Photo
            </button>
          </div>
        )}

        {/* PREVIEW */}
        {image && (
          <div className="mt-5 text-center">
            <p className="text-sm text-gray-500 mb-2">Preview</p>
            <img
              src={image}
              className="w-36 mx-auto rounded-xl shadow-lg border"
            />
          </div>
        )}

        {/* SUBMIT */}
        <button
          onClick={handleSubmit}
          disabled={!image}
          className={`w-full mt-5 py-2.5 rounded-xl font-medium text-white transition-all duration-200
          ${
            image
              ? "bg-green-600 hover:bg-green-700 shadow-md"
              : "bg-gray-400 cursor-not-allowed"
          }`}
        >
          Submit
        </button>
      </div>
    </div>
  );
}

export default App;
