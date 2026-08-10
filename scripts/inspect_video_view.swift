import Foundation
import AVFoundation
import AppKit
import Vision

// Emits conservative visual evidence for the Python manifest builder.  This
// intentionally does not make a final camera decision by itself: a low score
// is reported as unknown rather than guessed.
guard CommandLine.arguments.count == 2 || CommandLine.arguments.count == 3 else {
    fputs("usage: inspect_video_view.swift <video> [sample-count]\n", stderr)
    exit(2)
}

let source = URL(fileURLWithPath: CommandLine.arguments[1])
let sampleCount = CommandLine.arguments.count == 3 ? max(3, Int(CommandLine.arguments[2]) ?? 9) : 9
let asset = AVURLAsset(url: source)
let duration = CMTimeGetSeconds(asset.duration)
guard duration.isFinite && duration > 0 else {
    fputs("could not determine video duration\n", stderr)
    exit(1)
}

let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero

var faces = 0
var poseSamples = 0
var shoulderRatios: [Double] = []
var hipRatios: [Double] = []
var evidenceFrames: [Int] = []

func median(_ values: [Double]) -> Double? {
    guard !values.isEmpty else { return nil }
    let sorted = values.sorted()
    return sorted[sorted.count / 2]
}

func valid(_ point: VNRecognizedPoint?) -> VNRecognizedPoint? {
    guard let point = point, point.confidence >= 0.35 else { return nil }
    return point
}

for index in 0..<sampleCount {
    let second = duration * Double(index + 1) / Double(sampleCount + 1)
    do {
        let cgImage = try generator.copyCGImage(at: CMTime(seconds: second, preferredTimescale: 600), actualTime: nil)
        let faceRequest = VNDetectFaceRectanglesRequest()
        let poseRequest = VNDetectHumanBodyPoseRequest()
        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        try handler.perform([faceRequest, poseRequest])
        if !(faceRequest.results ?? []).isEmpty { faces += 1 }
        guard let pose = (poseRequest.results ?? []).first else { continue }
        let points = try pose.recognizedPoints(.all)
        guard let leftShoulder = valid(points[.leftShoulder]),
              let rightShoulder = valid(points[.rightShoulder]),
              let root = valid(points[.root]) else { continue }
        let shoulderWidth = abs(Double(leftShoulder.location.x - rightShoulder.location.x))
        let shoulderY = (Double(leftShoulder.location.y) + Double(rightShoulder.location.y)) / 2
        let bodyHeight = max(0.01, abs(shoulderY - Double(root.location.y)))
        shoulderRatios.append(shoulderWidth / bodyHeight)
        if let leftHip = valid(points[.leftHip]), let rightHip = valid(points[.rightHip]) {
            hipRatios.append(abs(Double(leftHip.location.x - rightHip.location.x)) / bodyHeight)
        }
        poseSamples += 1
        evidenceFrames.append(index)
    } catch {
        continue
    }
}

let result: [String: Any] = [
    "sample_count": sampleCount,
    "face_ratio": Double(faces) / Double(sampleCount),
    "pose_sample_count": poseSamples,
    "median_shoulder_to_torso_ratio": median(shoulderRatios) as Any,
    "median_hip_to_torso_ratio": median(hipRatios) as Any,
    "evidence_sample_indexes": evidenceFrames
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
