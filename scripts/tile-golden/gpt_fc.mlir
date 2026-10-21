cuda_tile.module @m {
  entry @gpt_fc(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<64x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<64x32xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%11, %6] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
      %16 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %17 = make_tensor_view %16, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
      %18 = make_partition_view %17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
      %19, %20, %21 = get_tile_block_id : tile<i32>
      %22, %23 = load_view_tko weak %18[%6, %20] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %24 = mmaf %14, %22, %7 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %24 : tile<64x32xf64>
    }
    %25, %26, %27 = get_tile_block_id : tile<i32>
    %28 = constant <i32: 32> : tile<i32>
    %29 = muli %26, %28 : tile<i32>
    %30 = reshape %29 : tile<i32> -> tile<1x1xi32>
    %31 = broadcast %30 : tile<1x1xi32> -> tile<64x32xi32>
    %32 = iota : tile<64xi32>
    %33 = reshape %32 : tile<64xi32> -> tile<64x1xi32>
    %34 = broadcast %33 : tile<64x1xi32> -> tile<64x32xi32>
    %35 = constant <i32: 0> : tile<64x32xi32>
    %36 = muli %34, %35 : tile<64x32xi32>
    %37 = addi %31, %36 : tile<64x32xi32>
    %38 = iota : tile<32xi32>
    %39 = reshape %38 : tile<32xi32> -> tile<1x32xi32>
    %40 = broadcast %39 : tile<1x32xi32> -> tile<64x32xi32>
    %41 = addi %37, %40 : tile<64x32xi32>
    %42 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %43 = broadcast %42 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %44 = offset %43, %41 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %45, %46 = load_ptr_tko weak %44 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %47 = addf %5, %45 rounding<nearest_even> : tile<64x32xf64>
    %48 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %49 = make_tensor_view %48, shape = [64, 128], strides = [128, 1] : tensor_view<64x128xf64, strides=[128, 1]>
    %50 = make_partition_view %49 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>
    %51, %52, %53 = get_tile_block_id : tile<i32>
    %54, %55, %56 = get_tile_block_id : tile<i32>
    %57 = store_view_tko weak %47, %50[%51, %55] token=%0 : tile<64x32xf64>, partition_view<tile=(64x32), padding_value = zero, tensor_view<64x128xf64, strides=[128, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
