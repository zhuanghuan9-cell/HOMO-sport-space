#!/usr/bin/env swift
// Produce a one-channel person mask for a still frame.  The Python renderer
// caches this result; it is deliberately independent from pose confidence so
// label placement never falls back to guessing a person's silhouette.
import Foundation
import Vision
import CoreImage
import ImageIO

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("usage: segment_person.swift INPUT_IMAGE OUTPUT_MASK.png\n", stderr)
    exit(64)
}

let inputURL = URL(fileURLWithPath: arguments[1])
let outputURL = URL(fileURLWithPath: arguments[2])
guard let source = CGImageSourceCreateWithURL(inputURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fputs("cannot read input image\n", stderr)
    exit(65)
}

let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = .balanced
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
do {
    try handler.perform([request])
    guard let result = request.results?.first as? VNPixelBufferObservation else {
        fputs("person segmentation returned no mask\n", stderr)
        exit(66)
    }
    let ciImage = CIImage(cvPixelBuffer: result.pixelBuffer)
    try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    let context = CIContext(options: nil)
    try context.writePNGRepresentation(of: ciImage, to: outputURL, format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
} catch {
    fputs("person segmentation failed: \(error)\n", stderr)
    exit(68)
}
