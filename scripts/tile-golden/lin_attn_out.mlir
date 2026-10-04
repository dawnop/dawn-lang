cuda_tile.module @m {
  entry @lin_attn_out(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %12 = constant <f64: 0.0> : tile<32x32xf64>
    %13 = cmpf greater_than ordered %10, %12 : tile<32x32xf64> -> tile<32x32xi1>
    %14 = constant <f64: 1.0> : tile<32x32xf64>
    %15 = addf %10, %14 rounding<nearest_even> : tile<32x32xf64>
    %16 = exp %10 : tile<32x32xf64>
    %17 = select %13, %15, %16 : tile<32x32xi1>, tile<32x32xf64>
    %18 = constant <i32: 0> : tile<i32>
    %19 = reshape %18 : tile<i32> -> tile<1x1xi32>
    %20 = broadcast %19 : tile<1x1xi32> -> tile<32x32xi32>
    %21 = iota : tile<32xi32>
    %22 = reshape %21 : tile<32xi32> -> tile<32x1xi32>
    %23 = broadcast %22 : tile<32x1xi32> -> tile<32x32xi32>
    %24 = constant <i32: 32> : tile<32x32xi32>
    %25 = muli %23, %24 : tile<32x32xi32>
    %26 = addi %20, %25 : tile<32x32xi32>
    %27 = iota : tile<32xi32>
    %28 = reshape %27 : tile<32xi32> -> tile<1x32xi32>
    %29 = broadcast %28 : tile<1x32xi32> -> tile<32x32xi32>
    %30 = constant <i32: 0> : tile<32x32xi32>
    %31 = muli %29, %30 : tile<32x32xi32>
    %32 = addi %26, %31 : tile<32x32xi32>
    %33 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %34 = broadcast %33 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %35 = offset %34, %32 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %36, %37 = load_ptr_tko weak %35 token=%11 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %38 = constant <i32: 0> : tile<i32>
    %39 = constant <i32: 0> : tile<i32>
    %40 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %41 = make_tensor_view %40, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %42 = make_partition_view %41 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %43, %44 = load_view_tko weak %42[%38, %39] token=%37 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %45 = constant <f64: 0.0> : tile<32x32xf64>
    %46 = mmaf %17, %43, %45 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %47 = mmaf %17, %36, %45 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %48 = divf %46, %47 rounding<nearest_even> : tile<32x32xf64>
    %49 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %50 = make_tensor_view %49, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %51 = make_partition_view %50 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %52 = store_view_tko weak %48, %51[%4, %8] token=%44 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
