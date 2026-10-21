cuda_tile.module @m {
  entry @llama_qkv(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<64x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 4> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<64x32xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %16, %17, %18 = get_num_tile_blocks : tile<i32>
      %19 = constant <i32: 32> : tile<i32>
      %20 = muli %17, %19 : tile<i32>
      %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %22 = make_tensor_view %21, shape = [%20, 128], strides = [128, 1] : tile<i32> -> tensor_view<?x128xf64, strides=[128, 1]>
      %23 = make_partition_view %22 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %24, %25, %26 = get_tile_block_id : tile<i32>
      %27, %28 = load_view_tko weak %23[%25, %6] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<?x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %29 = permute %27 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %30 = mmaf %14, %29, %7 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %30 : tile<64x32xf64>
    }
    %31, %32, %33 = get_num_tile_blocks : tile<i32>
    %34 = constant <i32: 64> : tile<i32>
    %35 = muli %32, %34 : tile<i32>
    %36 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %37 = make_tensor_view %36, shape = [%35, 32], strides = [32, 1] : tile<i32> -> tensor_view<?x32xf64, strides=[32, 1]>
    %38 = make_partition_view %37 : partition_view<tile=(64x32), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %39, %40, %41 = get_tile_block_id : tile<i32>
    %42, %43, %44 = get_tile_block_id : tile<i32>
    %45 = store_view_tko weak %5, %38[%40, %42] token=%0 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
