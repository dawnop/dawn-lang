cuda_tile.module @m {
  entry @gpt_dense(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<64x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<64x32xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%13, %7] token=%9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %18 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %19 = make_tensor_view %18, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %20 = make_partition_view %19 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %21, %22, %23 = get_tile_block_id : tile<i32>
      %24, %25 = load_view_tko weak %20[%7, %22] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %26 = mmaf %16, %24, %8 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %26, %25 : tile<64x32xf64>, token
    }
    %27, %28, %29 = get_tile_block_id : tile<i32>
    %30 = constant <i32: 32> : tile<i32>
    %31 = muli %28, %30 : tile<i32>
    %32 = reshape %31 : tile<i32> -> tile<1x1xi32>
    %33 = broadcast %32 : tile<1x1xi32> -> tile<64x32xi32>
    %34 = iota : tile<64xi32>
    %35 = reshape %34 : tile<64xi32> -> tile<64x1xi32>
    %36 = broadcast %35 : tile<64x1xi32> -> tile<64x32xi32>
    %37 = constant <i32: 0> : tile<64x32xi32>
    %38 = muli %36, %37 : tile<64x32xi32>
    %39 = addi %33, %38 : tile<64x32xi32>
    %40 = iota : tile<32xi32>
    %41 = reshape %40 : tile<32xi32> -> tile<1x32xi32>
    %42 = broadcast %41 : tile<1x32xi32> -> tile<64x32xi32>
    %43 = addi %39, %42 : tile<64x32xi32>
    %44 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %45 = broadcast %44 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %46 = offset %45, %43 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %47, %48 = load_ptr_tko weak %46 token=%6 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %49 = addf %5, %47 rounding<nearest_even> : tile<64x32xf64>
    %50 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %51 = make_tensor_view %50, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %52 = make_partition_view %51 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %53, %54, %55 = get_tile_block_id : tile<i32>
    %56, %57, %58 = get_tile_block_id : tile<i32>
    %59 = store_view_tko weak %49, %52[%53, %57] token=%48 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
