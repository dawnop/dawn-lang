cuda_tile.module @m {
  entry @attr_ftz(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = ftof %12 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %15 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %18, %19 = load_view_tko weak %17[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %20 = ftof %18 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %21 = addf %14, %20 rounding<nearest_even> : tile<128xf32>
    %22 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %23, %24, %25 = get_num_tile_blocks : tile<i32>
    %26 = constant <i32: 512> : tile<i32>
    %27 = muli %23, %26 : tile<i32>
    %28 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %29 = make_tensor_view %28, shape = [%27], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %30 = make_partition_view %29 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %31 = constant <i32: 4> : tile<i32>
    %32 = muli %9, %31 : tile<i32>
    %33 = store_view_tko weak %22, %30[%32] token=%19 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %34 = addf %14, %20 rounding<nearest_even> flush_to_zero : tile<128xf32>
    %35 = ftof %34 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %36 = constant <i32: 4> : tile<i32>
    %37 = muli %9, %36 : tile<i32>
    %38 = constant <i32: 1> : tile<i32>
    %39 = addi %37, %38 : tile<i32>
    %40 = store_view_tko weak %35, %30[%39] token=%33 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %41 = mulf %14, %20 rounding<nearest_even> : tile<128xf32>
    %42 = ftof %41 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %43 = constant <i32: 4> : tile<i32>
    %44 = muli %9, %43 : tile<i32>
    %45 = constant <i32: 2> : tile<i32>
    %46 = addi %44, %45 : tile<i32>
    %47 = store_view_tko weak %42, %30[%46] token=%40 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %48 = mulf %14, %20 rounding<nearest_even> flush_to_zero : tile<128xf32>
    %49 = ftof %48 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %50 = constant <i32: 4> : tile<i32>
    %51 = muli %9, %50 : tile<i32>
    %52 = constant <i32: 3> : tile<i32>
    %53 = addi %51, %52 : tile<i32>
    %54 = store_view_tko weak %49, %30[%53] token=%47 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
