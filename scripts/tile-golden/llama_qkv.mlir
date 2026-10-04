cuda_tile.module @m {
  entry @llama_qkv(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<64x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 4> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<64x32xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%13, %7] token=%9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %18, %19, %20 = get_num_tile_blocks : tile<i32>
      %21 = constant <i32: 32> : tile<i32>
      %22 = muli %19, %21 : tile<i32>
      %23 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %24 = make_tensor_view %23, shape = [%22, 128], strides = [128, 1] : tile<i32> -> tensor_view<?x128xf64, strides=[128, 1]>
      %25 = make_partition_view %24 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %26, %27, %28 = get_tile_block_id : tile<i32>
      %29, %30 = load_view_tko weak %25[%27, %7] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %31 = permute %29 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %32 = mmaf %16, %31, %8 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %32, %30 : tile<64x32xf64>, token
    }
    %33, %34, %35 = get_tile_block_id : tile<i32>
    %36 = constant <i32: 2048> : tile<i32>
    %37 = muli %34, %36 : tile<i32>
    %38 = reshape %37 : tile<i32> -> tile<1x1xi32>
    %39 = broadcast %38 : tile<1x1xi32> -> tile<64x32xi32>
    %40 = iota : tile<64xi32>
    %41 = reshape %40 : tile<64xi32> -> tile<64x1xi32>
    %42 = broadcast %41 : tile<64x1xi32> -> tile<64x32xi32>
    %43 = constant <i32: 32> : tile<64x32xi32>
    %44 = muli %42, %43 : tile<64x32xi32>
    %45 = addi %39, %44 : tile<64x32xi32>
    %46 = iota : tile<32xi32>
    %47 = reshape %46 : tile<32xi32> -> tile<1x32xi32>
    %48 = broadcast %47 : tile<1x32xi32> -> tile<64x32xi32>
    %49 = addi %45, %48 : tile<64x32xi32>
    %50 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %51 = broadcast %50 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %52 = offset %51, %49 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %53 = store_ptr_tko weak %52, %5 token=%6 : tile<64x32xptr<f64>>, tile<64x32xf64> -> token
    return
  }
}
