import Foundation
import AVFoundation
import AppKit

guard CommandLine.arguments.count == 3 || CommandLine.arguments.count == 6 else {
    fputs("usage: extract_video_frames.swift <video> <output-dir> [start-sec end-sec sample-count]\n", stderr)
    exit(2)
}

let videoURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)

let asset = AVURLAsset(url: videoURL)
let seconds = CMTimeGetSeconds(asset.duration)
guard seconds.isFinite, seconds > 0 else {
    fputs("could not determine duration\n", stderr)
    exit(1)
}

let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero

let startSecond = CommandLine.arguments.count == 6 ? Double(CommandLine.arguments[3])! : 0
let endSecond = CommandLine.arguments.count == 6 ? Double(CommandLine.arguments[4])! : seconds
let sampleCount = CommandLine.arguments.count == 6 ? Int(CommandLine.arguments[5])! : max(2, Int(ceil((endSecond - startSecond) * 30)) + 1)
print("duration=\(String(format: "%.3f", seconds)) range=\(startSecond)-\(endSecond) sample_count=\(sampleCount)")

for index in 0..<sampleCount {
    let second = startSecond + (endSecond - startSecond) * Double(index) / Double(max(1, sampleCount - 1))
    do {
        let cgImage = try generator.copyCGImage(at: CMTime(seconds: second, preferredTimescale: 600), actualTime: nil)
        let bitmap = NSBitmapImageRep(cgImage: cgImage)
        guard let data = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.9]) else { continue }
        let name = String(format: "frame_%04d_%06.2fs.jpg", index, second)
        try data.write(to: outputURL.appendingPathComponent(name))
        print(name)
    } catch {
        fputs("frame \(index) failed: \(error)\n", stderr)
    }
}
