cuda_tile.module @m {
  entry @matvec(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<64x64xi32>
    %4 = iota : tile<64xi32>
    %5 = reshape %4 : tile<64xi32> -> tile<64x1xi32>
    %6 = broadcast %5 : tile<64x1xi32> -> tile<64x64xi32>
    %7 = constant <i32: 0> : tile<64x64xi32>
    %8 = muli %6, %7 : tile<64x64xi32>
    %9 = addi %3, %8 : tile<64x64xi32>
    %10 = iota : tile<64xi32>
    %11 = reshape %10 : tile<64xi32> -> tile<1x64xi32>
    %12 = broadcast %11 : tile<1x64xi32> -> tile<64x64xi32>
    %13 = addi %9, %12 : tile<64x64xi32>
    %14 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %15 = broadcast %14 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %16 = offset %15, %13 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %19 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %20 = make_tensor_view %19, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %21 = make_partition_view %20 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %22, %23, %24 = get_tile_block_id : tile<i32>
    %25, %26, %27 = get_tile_block_id : tile<i32>
    %28, %29 = load_view_tko weak %21[%22, %26] token=%18 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf64>, token
    %30 = mulf %28, %17 rounding<nearest_even> : tile<64x64xf64>
    %31 = reduce %30 dim=1 identities=[0.0 : f64] : tile<64x64xf64> -> tile<64xf64> (%32: tile<f64>, %33: tile<f64>) {
      %34 = addf %32, %33 rounding<nearest_even> : tile<f64>
      yield %34 : tile<f64>
    }
    %35 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %36 = make_tensor_view %35, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %37 = make_partition_view %36 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %38 = store_view_tko weak %31, %37[%22] token=%29 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
