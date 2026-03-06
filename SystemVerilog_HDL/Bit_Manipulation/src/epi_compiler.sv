//module epi_compiler #(
//	parameter IMAGE_DIM,
//	parameter IMAGE_DIM_BS
//	)(
//	input wire clk,
//	input wire pixel_valid_in,
//	input wire soc_in,
//	input wire eoc_in,
//	input wire solf_in,
//	input wire eolf_in,
//	input wire [14:0] pixel_in,
//	output logic epi_valid_out,
//	output logic [14:0] epi_frame_out [0:(9<<IMAGE_DIM_BS)-1],
//	output logic [IMAGE_DIM_BS-1:0] epi_idx_out,
//	output logic orientation_out
//);
//
//	// ---------- Define parameters and variables ----------
//
//	// Initialise pixel buffer
//	// Assume 15 bit input and we need to store 8 full frames plus one line
//	// After 8 frames and one line, buffer is full and contains 1 EPI
//	// It saves space to just save all 17 frames in one buffer
//	// This is because one capture overlaps between horizontal and vertical
//	localparam int unsigned EPI_BUFFER_SIZE  = (17 << (IMAGE_DIM_BS + IMAGE_DIM_BS));
//	localparam int unsigned EPI_BUFFER_PTR_W = $clog2(EPI_BUFFER_SIZE);
//
//	logic [14:0] pixel_buffer_epi [0:EPI_BUFFER_SIZE-1];
//
//	// Circular buffer pointer
//	// Points to the physical index corresponding to logical index 0
//	logic [EPI_BUFFER_PTR_W-1:0] pixel_buffer_head = 0;
//
//	// Counters for input logging
//	logic [4:0] capture_in_count             = 0;
//	logic [IMAGE_DIM_BS-1:0] row_in_count    = 0;
//	logic [IMAGE_DIM_BS-1:0] column_in_count = 0;
//	
//	// Flag to note if we are recieving a light field
//	logic in_lf_flag = 0;
//
//	// ----------  Shift incoming pixels into buffers ----------
//	always_ff @(posedge clk) begin : EPI_Buffer
//		// When we recieve the start of light field flag we note that we are in a light field
//		if (solf_in) begin
//			in_lf_flag <= 1;
//			capture_in_count <= 0;
//		end
//		
//		// When we recieve the end of light field flag we note that we are no longer in a light field
//		else if (eolf_in) begin
//			in_lf_flag <= 0;
//			capture_in_count <= 0;
//		end
//
//		if (in_lf_flag) begin
//			if (pixel_valid_in) begin
//				// When we are in a light field, only advance the EPI buffer when the input pixel is valid
//				// Circular buffer behaviour:
//				// overwrite the oldest element, then move the head forward
//				pixel_buffer_epi[pixel_buffer_head] <= pixel_in;
//
//				if (pixel_buffer_head == EPI_BUFFER_SIZE-1) begin
//					pixel_buffer_head <= 0;
//				end
//				else begin
//					pixel_buffer_head <= pixel_buffer_head + EPI_BUFFER_PTR_W'(1);
//				end
//				
//				// Reset counters when new captures are input
//				if (soc_in || eoc_in) begin
//					row_in_count    <= 0;
//					column_in_count <= 0;
//				end
//				
//				// Increment capture counters when soc_in is detected but without solf_in
//				if (soc_in && !(solf_in)) begin
//					capture_in_count <= capture_in_count + $bits(capture_in_count)'(1);
//				end
//				
//				// Increment row and column counters whilst pixels are coming in
//				// When all columns in a row exhausted, start next row
//				if (column_in_count == IMAGE_DIM-1) begin
//					column_in_count <= 0;
//					row_in_count    <= row_in_count + $bits(row_in_count)'(1);
//				end
//
//				// Increment column count for every new valid pixel
//				else begin
//					column_in_count <= column_in_count + $bits(column_in_count)'(1);
//				end
//			end
//		end
//		
//		// When we are not in a light field, continuously push zeros through the circular buffer
//		else begin
//			pixel_buffer_epi[pixel_buffer_head] <= 0;
//
//			if (pixel_buffer_head == EPI_BUFFER_SIZE-1) begin
//				pixel_buffer_head <= 0;
//			end
//			else begin
//				pixel_buffer_head <= pixel_buffer_head + EPI_BUFFER_PTR_W'(1);
//			end
//		end
//	end
//	
//	// ----------  Use pixels in buffers to create EPIs ----------
//	always_ff @(posedge clk) begin : EPI_Extractor
//		// Horizontal logic (orientation_out = 0)
//		// Vertical logic (orientation_out = 1)
//		
//		// For now just output a what's in the pixel buffer and is considered invalid
//		for (int idx = 0; idx < (9<<IMAGE_DIM_BS)-1; idx++) begin
//			epi_frame_out[idx] <= pixel_buffer_epi[idx];
//		end
//		
//		epi_valid_out   <= 0;
//		epi_idx_out     <= 0;
//		orientation_out <= 0;
//	end
//
//endmodule