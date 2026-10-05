cuda_tile.module @m {
  entry @attr_round(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %21 = addf %14, %20 rounding<negative_inf> : tile<128xf32>
    %22 = ftof %21 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %23 = reshape %22 : tile<128xf64> -> tile<1x1x128xf64>
    %24, %25, %26 = get_num_tile_blocks : tile<i32>
    %27 = constant <i32: 1> : tile<i32>
    %28 = muli %24, %27 : tile<i32>
    %29 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [%28, 6, 128], strides = [768, 128, 1] : tile<i32> -> tensor_view<?x6x128xf64, strides=[768, 128, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38 = constant <i32: 8> : tile<i32>
    %39 = muli %33, %38 : tile<i32>
    %40 = store_view_tko weak %23, %31[%9, %39, %37] token=%19 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %41 = addf %14, %20 rounding<positive_inf> : tile<128xf32>
    %42 = ftof %41 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %43 = reshape %42 : tile<128xf64> -> tile<1x1x128xf64>
    %44 = constant <i32: 8> : tile<i32>
    %45 = muli %33, %44 : tile<i32>
    %46 = constant <i32: 1> : tile<i32>
    %47 = addi %45, %46 : tile<i32>
    %48 = store_view_tko weak %43, %31[%9, %47, %37] token=%40 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %49 = mulf %14, %20 rounding<negative_inf> : tile<128xf32>
    %50 = ftof %49 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %51 = reshape %50 : tile<128xf64> -> tile<1x1x128xf64>
    %52 = constant <i32: 8> : tile<i32>
    %53 = muli %33, %52 : tile<i32>
    %54 = constant <i32: 2> : tile<i32>
    %55 = addi %53, %54 : tile<i32>
    %56 = store_view_tko weak %51, %31[%9, %55, %37] token=%48 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %57 = mulf %14, %20 rounding<positive_inf> : tile<128xf32>
    %58 = ftof %57 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %59 = reshape %58 : tile<128xf64> -> tile<1x1x128xf64>
    %60 = constant <i32: 8> : tile<i32>
    %61 = muli %33, %60 : tile<i32>
    %62 = constant <i32: 3> : tile<i32>
    %63 = addi %61, %62 : tile<i32>
    %64 = store_view_tko weak %59, %31[%9, %63, %37] token=%56 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %65 = divf %14, %20 rounding<negative_inf> : tile<128xf32>
    %66 = ftof %65 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %67 = reshape %66 : tile<128xf64> -> tile<1x1x128xf64>
    %68 = constant <i32: 8> : tile<i32>
    %69 = muli %33, %68 : tile<i32>
    %70 = constant <i32: 4> : tile<i32>
    %71 = addi %69, %70 : tile<i32>
    %72 = store_view_tko weak %67, %31[%9, %71, %37] token=%64 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    %73 = divf %14, %20 rounding<positive_inf> : tile<128xf32>
    %74 = ftof %73 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %75 = reshape %74 : tile<128xf64> -> tile<1x1x128xf64>
    %76 = constant <i32: 8> : tile<i32>
    %77 = muli %33, %76 : tile<i32>
    %78 = constant <i32: 5> : tile<i32>
    %79 = addi %77, %78 : tile<i32>
    %80 = store_view_tko weak %75, %31[%9, %79, %37] token=%72 : tile<1x1x128xf64>, partition_view<tile=(1x1x128), padding_value = zero, tensor_view<?x6x128xf64, strides=[768, 128, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
